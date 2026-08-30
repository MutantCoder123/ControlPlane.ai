"""Seeded canaries - our false-negative instrument.

D25, and the hardest thing the Round 2 brief asks: "how you would define,
measure, and report false positive/negative rates and overall system
trustworthiness to a skeptical stakeholder."

THE UNCOMFORTABLE ASYMMETRY (IDEATION section 14.1)
---------------------------------------------------
False positives are directly measurable: every block and every flag can be
shown to a reviewer, and disagreement gives a true FP rate.

False negatives are NOT. We cannot count what we never detected - the same
knowledge gap that causes the miss also hides it. Any team quoting a precise
FN rate is quoting a number they cannot have.

WHAT WE DO INSTEAD
------------------
Inject values we KNOW are sensitive into traffic and measure how many come
back caught. That gives a real, defensible FN estimate *on the seeded
distribution* - and the caveat travels with the number rather than sitting in
a footnote. `CanaryReport.__str__` cannot render the catch rate without also
rendering what was seeded and the confidence interval, by construction.

The other two proxies (IDEATION 14.1) are dual-detector disagreement and
downstream incident correlation. Neither is built here: the first needs a
second detector, the second needs production. Both are named in the report's
`not_measured` field rather than quietly omitted.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass, field


@dataclass(frozen=True)
class Canary:
    """A value we planted, and therefore know the truth about."""

    canary_id: str
    category: str
    value: str
    governed: bool = True


@dataclass
class CanaryOutcome:
    canary: Canary
    caught: bool
    caught_by: str | None = None      # "known_value" | "pattern" | None


@dataclass
class CanaryReport:
    """A catch rate that cannot be quoted without its caveat."""

    outcomes: list[CanaryOutcome] = field(default_factory=list)
    profile: str = ""

    @property
    def total(self) -> int:
        return len(self.outcomes)

    @property
    def caught(self) -> int:
        return sum(1 for o in self.outcomes if o.caught)

    @property
    def catch_rate(self) -> float:
        return self.caught / self.total if self.total else 0.0

    @property
    def miss_rate(self) -> float:
        """The FN estimate. On the seeded distribution, and only there."""
        return 1.0 - self.catch_rate if self.total else 0.0

    @property
    def confidence_interval(self) -> tuple[float, float]:
        """Wilson score interval, 95%.

        IDEATION 14.3: show the trend, the method, and the interval - not a
        single number on a dial. Twelve canaries and a 100% catch rate is not
        the same claim as twelve hundred, and the interval is what says so.
        """
        n = self.total
        if n == 0:
            return (0.0, 0.0)
        z = 1.96
        p = self.catch_rate
        denom = 1 + z * z / n
        centre = (p + z * z / (2 * n)) / denom
        margin = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
        return (max(0.0, centre - margin), min(1.0, centre + margin))

    @property
    def by_category(self) -> dict[str, tuple[int, int]]:
        out: dict[str, list[int]] = {}
        for outcome in self.outcomes:
            bucket = out.setdefault(outcome.canary.category, [0, 0])
            bucket[1] += 1
            bucket[0] += int(outcome.caught)
        return {k: (v[0], v[1]) for k, v in sorted(out.items())}

    @property
    def seeded_distribution(self) -> dict[str, int]:
        """The caveat, as data. Travels with every catch rate we publish."""
        dist: dict[str, int] = {}
        for outcome in self.outcomes:
            dist[outcome.canary.category] = dist.get(outcome.canary.category, 0) + 1
        return dict(sorted(dist.items()))

    @property
    def misses(self) -> list[Canary]:
        return [o.canary for o in self.outcomes if not o.caught]

    #: Named rather than omitted. A metrics report that lists only what it
    #: measured invites the reader to assume it measured everything.
    not_measured: tuple[str, ...] = (
        "dual-detector disagreement (needs a second, slower detector)",
        "downstream incident correlation (needs production traffic)",
        "unknown-unknowns: values in no category we thought to seed",
    )

    def as_dict(self) -> dict:
        low, high = self.confidence_interval
        return {
            "profile": self.profile,
            "canaries_seeded": self.total,
            "caught": self.caught,
            "catch_rate": round(self.catch_rate, 4),
            "estimated_miss_rate": round(self.miss_rate, 4),
            "confidence_interval_95": [round(low, 4), round(high, 4)],
            "seeded_distribution": self.seeded_distribution,
            "by_category": {k: f"{c}/{t}" for k, (c, t) in self.by_category.items()},
            "caveat": (
                "This is a false-negative estimate ON THE SEEDED DISTRIBUTION "
                "shown above. It says nothing about categories we did not seed."
            ),
            "not_measured": list(self.not_measured),
        }

    def __str__(self) -> str:
        low, high = self.confidence_interval
        return (
            f"canary catch rate {self.catch_rate:.1%} "
            f"({self.caught}/{self.total}, 95% CI {low:.1%}-{high:.1%}) "
            f"on seeded distribution {self.seeded_distribution} - "
            f"says nothing about categories we did not seed"
        )


class CanarySuite:
    """Plants known-sensitive values and measures how many come back caught."""

    #: Structurally valid so the checksum tier has a fair chance, and outside
    #: any real allocation. A canary the detector could never catch measures
    #: nothing except our ability to write an impossible test.
    TEMPLATES: dict[str, tuple[str, ...]] = {
        "payment_card": ("4539578763621486", "5425233430109903", "374245455400126"),
        "aadhaar": ("234123412346", "999999990019"),
        # AWS key ids are AKIA + exactly 16 chars. A 19-character canary
        # matches nothing and quietly depresses the catch rate - see the
        # self-check test, which exists because that happened.
        "api_key": ("sk-canary000111222333444555666777", "AKIAIOSFODNN7CANARY1"),
        "iban": ("GB82WEST12345698765432", "DE89370400440532013000"),
    }

    def __init__(self, seed: int = 20260830) -> None:
        self._rng = random.Random(seed)
        self._counter = 0

    def mint(self, category: str, *, governed: bool = True) -> Canary:
        options = self.TEMPLATES.get(category)
        if not options:
            raise KeyError(f"no canary template for {category!r}")
        self._counter += 1
        return Canary(
            canary_id=f"canary-{self._counter:04d}",
            category=category,
            value=self._rng.choice(options),
            governed=governed,
        )

    def mint_batch(self, plan: dict[str, int]) -> list[Canary]:
        """`{"payment_card": 10, "api_key": 5}` -> a seeded distribution."""
        return [self.mint(c) for c, n in sorted(plan.items()) for _ in range(n)]

    @staticmethod
    def plant(canary: Canary, carrier: str = "Please review this record: {}.") -> str:
        return carrier.format(canary.value)

    def run(self, canaries: list[Canary], scan, *, profile: str = "") -> CanaryReport:
        """Plant each canary, scan the result, record whether it was caught.

        `scan` is any callable returning something with `.findings` - the
        substitution engine's `scan_inbound` fits directly.
        """
        report = CanaryReport(profile=profile)
        for canary in canaries:
            result = scan(self.plant(canary))
            findings = getattr(result, "findings", [])
            hit = next(
                (f for f in findings if canary.value.replace(" ", "") in canary.value),
                None,
            )
            caught = bool(findings)
            report.outcomes.append(
                CanaryOutcome(
                    canary=canary,
                    caught=caught,
                    caught_by=(findings[0].kind if caught else None),
                )
            )
        return report
