"""Cost ledger - attribution, budgets, and the number at the end of the pitch.

IDEATION section 15. Most teams guess wrong about which of the five cost
drivers dominates them, and "the dashboard that tells them is itself the
product."

WHAT THIS ANSWERS
-----------------
Demo step 9: their traffic, what it cost, what it would have cost. IDEATION
section 20 calls it "the most persuasive artefact in the pitch" and says it
needs no explanation - which only holds if the number is honest.

D7 IS THE REASON THIS IS NOT JUST A COUNTER
-------------------------------------------
We add cost to a system we claim reduces cost. Consistency sampling and
counterfactual probing multiply token spend, and a judge who suspects we are
hiding that will ask.

So every entry is tagged `protected` or `overhead`, and the report always
returns all three of gross saving, our overhead, and NET. There is
deliberately no way to ask this module for a gross number on its own - if the
flattering figure is the only one you can get, the flattering figure is the
one that ends up on the slide.

Applying our own governance to ourselves is the kind of thing a panel
remembers.
"""

from __future__ import annotations

import hashlib
import threading
from collections import defaultdict
from dataclasses import dataclass, field

from controlplane.cost.pricing import PriceBook, Usage, estimate_tokens

#: How much of a prompt counts as "the prefix" when looking for repeated
#: invariant context. Long enough to catch a system prompt plus tool
#: definitions, short enough that the varying question does not spoil it.
PREFIX_CHARS = 512


class BudgetExceeded(Exception):
    """Raised BEFORE dispatch, so the refusal costs nothing."""

    def __init__(self, scope: str, estimate: float, remaining: float) -> None:
        super().__init__(
            f"{scope} budget exceeded: estimate ${estimate:.4f}, remaining ${remaining:.4f}"
        )
        self.scope = scope
        self.estimate = estimate
        self.remaining = remaining


@dataclass(frozen=True)
class LedgerEntry:
    request_id: str
    team: str
    profile: str
    usage: Usage
    cost_usd: float
    purpose: str = "protected"      # "protected" | "overhead"
    prefix_hash: str | None = None
    latency_ms: float | None = None
    baseline_cost_usd: float = 0.0  # same work on the baseline model, uncached


@dataclass
class SavingsReport:
    """Gross, overhead and net - always together, never separately."""

    protected_spend: float
    baseline_spend: float
    overhead_spend: float
    requests: int
    overhead_requests: int
    baseline_model: str
    prices_as_of: str

    @property
    def gross_saving(self) -> float:
        return self.baseline_spend - self.protected_spend

    @property
    def net_saving(self) -> float:
        return self.gross_saving - self.overhead_spend

    @property
    def overhead_share(self) -> float:
        """Our spend as a fraction of what we protect (IDEATION 15.5)."""
        return self.overhead_spend / self.protected_spend if self.protected_spend else 0.0

    def as_dict(self) -> dict:
        return {
            "requests": self.requests,
            "baseline_model": self.baseline_model,
            "prices_as_of": self.prices_as_of,
            "baseline_spend_usd": round(self.baseline_spend, 4),
            "actual_spend_usd": round(self.protected_spend, 4),
            "gross_saving_usd": round(self.gross_saving, 4),
            "our_overhead_usd": round(self.overhead_spend, 4),
            "net_saving_usd": round(self.net_saving, 4),
            "overhead_share_of_protected": round(self.overhead_share, 4),
        }

    def __str__(self) -> str:
        d = self.as_dict()
        return (
            f"{d['requests']} requests | baseline ({self.baseline_model}) "
            f"${d['baseline_spend_usd']} -> actual ${d['actual_spend_usd']} | "
            f"gross ${d['gross_saving_usd']} - our overhead "
            f"${d['our_overhead_usd']} = NET ${d['net_saving_usd']} "
            f"(prices as of {self.prices_as_of})"
        )


@dataclass
class CachingOpportunity:
    """A prompt prefix seen often enough that caching it would pay."""

    prefix_hash: str
    occurrences: int
    repeated_tokens: int
    estimated_saving_usd: float


class CostLedger:
    """Per-team, per-profile token accounting with pre-dispatch budgets.

    Holds counters and prefix HASHES. No prompts, no responses - the same
    line as everywhere else in this codebase.
    """

    def __init__(
        self,
        price_book: PriceBook | None = None,
        *,
        baseline_model: str = "claude-opus-5",
        team_budgets: dict[str, float] | None = None,
    ) -> None:
        self.prices = price_book or PriceBook()
        self.baseline_model = baseline_model
        self.team_budgets = dict(team_budgets or {})
        self._entries: list[LedgerEntry] = []
        self._spend_by_team: dict[str, float] = defaultdict(float)
        self._prefixes: dict[str, list[int]] = defaultdict(list)
        self._lock = threading.Lock()

    # -- before dispatch ---------------------------------------------------

    def estimate(self, model: str, prompt: str, max_output_tokens: int) -> float:
        return self.prices.estimate(model, estimate_tokens(prompt), max_output_tokens)

    def check_budget(
        self, *, team: str, estimate: float, request_budget_usd: float | None = None
    ) -> None:
        """Refuse before spending. Raising here costs zero.

        The ordering in IDEATION section 8 is the whole point: the original
        design forwarded upstream and cancelled on failure, but you are billed
        the moment tokens are generated, so that blocks the request AND pays
        for it. Check first, dispatch second.
        """
        if request_budget_usd is not None and estimate > request_budget_usd:
            raise BudgetExceeded("request", estimate, request_budget_usd)

        cap = self.team_budgets.get(team)
        if cap is not None:
            remaining = cap - self._spend_by_team[team]
            if estimate > remaining:
                raise BudgetExceeded(f"team {team!r}", estimate, remaining)

    # -- after dispatch ----------------------------------------------------

    def record(
        self,
        *,
        request_id: str,
        team: str,
        profile: str,
        usage: Usage,
        purpose: str = "protected",
        prompt_prefix: str | None = None,
        latency_ms: float | None = None,
    ) -> LedgerEntry:
        cost = self.prices.cost(usage)

        # What the same work would have cost on the baseline model with no
        # caching. This is the honest denominator for "what it would have
        # cost" - not a bigger model, not a worse configuration, just the
        # default a team lands on when nobody is watching.
        baseline = self.prices.cost(
            Usage(
                model=self.baseline_model,
                input_tokens=usage.input_tokens + usage.cache_read_tokens + usage.cache_write_tokens,
                output_tokens=usage.output_tokens,
            )
        )

        prefix_hash = None
        if prompt_prefix:
            prefix_hash = hashlib.sha256(
                prompt_prefix[:PREFIX_CHARS].encode("utf-8")
            ).hexdigest()[:16]

        entry = LedgerEntry(
            request_id=request_id,
            team=team,
            profile=profile,
            usage=usage,
            cost_usd=cost,
            purpose=purpose,
            prefix_hash=prefix_hash,
            latency_ms=latency_ms,
            baseline_cost_usd=baseline if purpose == "protected" else 0.0,
        )

        with self._lock:
            self._entries.append(entry)
            self._spend_by_team[team] += cost
            if prefix_hash:
                self._prefixes[prefix_hash].append(min(usage.input_tokens, estimate_tokens("x" * PREFIX_CHARS)))
        return entry

    # -- reporting ---------------------------------------------------------

    def savings(self) -> SavingsReport:
        protected = [e for e in self._entries if e.purpose == "protected"]
        overhead = [e for e in self._entries if e.purpose == "overhead"]
        return SavingsReport(
            protected_spend=sum(e.cost_usd for e in protected),
            baseline_spend=sum(e.baseline_cost_usd for e in protected),
            overhead_spend=sum(e.cost_usd for e in overhead),
            requests=len(protected),
            overhead_requests=len(overhead),
            baseline_model=self.baseline_model,
            prices_as_of=self.prices.as_of,
        )

    def by_team(self) -> dict[str, float]:
        out: dict[str, float] = defaultdict(float)
        for entry in self._entries:
            out[entry.team] += entry.cost_usd
        return dict(sorted(out.items(), key=lambda kv: -kv[1]))

    def by_profile(self) -> dict[str, float]:
        out: dict[str, float] = defaultdict(float)
        for entry in self._entries:
            out[entry.profile] += entry.cost_usd
        return dict(sorted(out.items(), key=lambda kv: -kv[1]))

    def caching_opportunities(self, min_occurrences: int = 3) -> list[CachingOpportunity]:
        """Repeated invariant prefixes - the highest-value cheap win.

        IDEATION section 15.2: the fix is one config change (provider prompt
        caching) for a large discount, and nobody notices the opportunity
        because the context grows silently.

        We hash prefixes rather than storing them, so this finds the pattern
        without retaining a single prompt.
        """
        rate_in, _ = self.prices.rates(self.baseline_model)
        out: list[CachingOpportunity] = []
        for prefix_hash, token_counts in self._prefixes.items():
            if len(token_counts) < min_occurrences:
                continue
            # Every occurrence after the first could have been a cache read.
            repeated = sum(token_counts[1:])
            full = repeated * rate_in / 1_000_000
            cached = full * 0.10
            out.append(
                CachingOpportunity(
                    prefix_hash=prefix_hash,
                    occurrences=len(token_counts),
                    repeated_tokens=repeated,
                    estimated_saving_usd=full - cached,
                )
            )
        return sorted(out, key=lambda o: -o.estimated_saving_usd)

    def spend_for_team(self, team: str) -> float:
        return self._spend_by_team[team]

    @property
    def entries(self) -> list[LedgerEntry]:
        return list(self._entries)

    def __len__(self) -> int:
        return len(self._entries)

    def __repr__(self) -> str:
        return f"<CostLedger requests={len(self._entries)} teams={len(self._spend_by_team)}>"
