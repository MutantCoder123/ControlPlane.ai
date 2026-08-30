"""Tiered decisions and human escalation.

D26. IDEATION section 12, and the Round 2 brief's Decision Logic area:
"confidence scoring, tiered responses (allow / edit / flag for review /
block), and clear rules for when a human should be pulled in."

Detection is worthless without a graded response. A binary allow/block forces
every uncertain finding into one of two wrong answers - either we interrupt
the user over a maybe, or we let it through because we were not sure enough
to stop it.

THE RULE THAT MAKES PROFILES LOAD-BEARING
-----------------------------------------
    The tier is a function of severity x confidence x profile,
    never of the finding alone.

The same detection resolves differently under `internal-knowledge` and
`customer-support`. Without this, route profiles are decoration.

OVER-FLAGGING IS TUNED, NOT SOLVED
----------------------------------
The brief names the failure precisely: too many flags and users learn to
dismiss them, which is worse than not flagging, because now there is a
control everyone believes is working.

Three mechanisms here, all deliberate trade-offs rather than fixes:

1. A per-profile FLAG BUDGET. Exceed it and flags are suppressed from the
   user and diverted to sampling instead. The budget is a policy value the
   customer sets - they own their own fatigue tolerance.
2. NO FLAG WITHOUT ACTIONABLE EVIDENCE. "Possible issue" is fatigue. "This
   figure varied across samples: 30 / 45 / 60 days" is a task. If we cannot
   say what to check, we do not interrupt.
3. The cascade upstream (IDEATION 11.5) means most traffic never reaches a
   checker at all.

WHERE A HUMAN COMES IN
----------------------
Not on every flag. On the MIDDLE of the confidence range - the extremes are
exactly where automation is reliable, and the middle is where it is not.
Escalating the middle is the honest use of a reviewer.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from enum import IntEnum

from controlplane.policy.profile import Profile


class Tier(IntEnum):
    """Ordered, so the strongest signal in a response decides the outcome."""

    ALLOW = 0
    ANNOTATE = 1
    REVIEW = 2
    BLOCK = 3

    @property
    def label(self) -> str:
        return self.name.lower()


class Escalation(str):
    """Why a human was pulled in. Kept as plain strings for the audit line."""


MID_BAND = "confidence in the mid-band"
PROFILE_RULE = "profile reviews every response"
POLICY_EXCEPTION = "policy exception requested"
NOVEL_PATTERN = "pattern has no prior"


@dataclass(frozen=True)
class Signal:
    """One thing worth deciding about.

    Deliberately not `Finding`: quality checks (hallucination, toxicity) will
    produce signals too, in a later phase, and the decision logic should not
    care which detector spoke. `reversible` is the axis that matters
    (IDEATION section 6) - not which of the three risk names applies, since
    a fabricated detail about a person is all three at once.
    """

    category: str
    kind: str                       # "known_value" | "pattern" | "quality" | ...
    confidence: float
    reversible: bool
    record_ref: str | None = None
    evidence: str | None = None     # what the user should actually check
    novel: bool = False             # no prior for this pattern

    @property
    def exemption_keys(self) -> tuple[str, ...]:
        keys = [self.category, f"{self.kind}:{self.category}"]
        if self.record_ref:
            keys.append(self.record_ref)
        return tuple(keys)


@dataclass(frozen=True)
class SignalOutcome:
    signal: Signal
    tier: Tier
    reason: str


@dataclass
class Decision:
    """What happens to one response, and why."""

    tier: Tier
    outcomes: list[SignalOutcome] = field(default_factory=list)
    escalations: list[str] = field(default_factory=list)
    suppressed: int = 0             # flags withheld because the budget was spent
    sampled: bool = False           # withheld but kept for measurement
    profile: str = ""
    policy_version: int = 0

    @property
    def needs_human(self) -> bool:
        return self.tier is Tier.REVIEW

    @property
    def blocked(self) -> bool:
        return self.tier is Tier.BLOCK

    @property
    def user_visible_flags(self) -> int:
        return sum(1 for o in self.outcomes if o.tier >= Tier.ANNOTATE)

    def audit_payload(self) -> dict:
        """Safe to hand straight to the audit log - references, never values."""
        return {
            "tier": self.tier.label,
            "profile": self.profile,
            "policy_version": self.policy_version,
            "escalations": sorted(set(self.escalations)),
            "suppressed": self.suppressed,
            "sampled": self.sampled,
            "signals": [
                {
                    "category": o.signal.category,
                    "kind": o.signal.kind,
                    "confidence": o.signal.confidence,
                    "record_ref": o.signal.record_ref,
                    "tier": o.tier.label,
                    "reason": o.reason,
                }
                for o in self.outcomes
            ],
        }


class FlagBudget:
    """Rolling per-profile cap on user-visible flags.

    STATELESSNESS CHECK (IDEATION section 3): this holds a fixed-length window
    of booleans - was that decision a flag, yes or no. No prompt, no response,
    no identifier, nothing about who asked. It is aggregate statistics about
    decisions, which is exactly the line drawn in section 13.1 between what
    the data plane may hold and what it may not.
    """

    __slots__ = ("_window", "_size")

    def __init__(self, window: int = 100) -> None:
        self._size = window
        self._window: dict[str, deque] = {}

    def rate_per_100(self, profile: str) -> float:
        window = self._window.get(profile)
        if not window:
            return 0.0
        return 100.0 * sum(window) / len(window)

    def would_exceed(self, profile: str, budget: int) -> bool:
        window = self._window.get(profile)
        if not window or len(window) < self._size:
            # Not enough history to judge. Under-flagging creates real
            # liability, so we do not throttle on a thin sample.
            return False
        return sum(window) >= budget

    def record(self, profile: str, flagged: bool) -> None:
        self._window.setdefault(profile, deque(maxlen=self._size)).append(bool(flagged))

    def reset(self, profile: str | None = None) -> None:
        if profile is None:
            self._window.clear()
        else:
            self._window.pop(profile, None)


class DecisionEngine:
    """Turns signals plus a profile into one graded outcome."""

    def __init__(self, budget: FlagBudget | None = None) -> None:
        self.budget = budget or FlagBudget()

    def decide(
        self,
        signals: list[Signal],
        profile: Profile,
        *,
        policy_version: int = 0,
        exception_requested: bool = False,
    ) -> Decision:
        decision = Decision(
            tier=Tier.ALLOW, profile=profile.name, policy_version=policy_version
        )
        low, high = profile.decision.review_band
        exempt = set(profile.decision.exempt)

        for signal in signals:
            tier, reason = self._tier_for(signal, profile, low, high, exempt)
            decision.outcomes.append(SignalOutcome(signal, tier, reason))
            if tier is Tier.REVIEW:
                decision.escalations.append(reason)

        if exception_requested:
            # The identifier-is-operand case (D16): "validate this account
            # number's checksum" cannot be answered on a substituted value.
            # That is a human decision, not a threshold.
            decision.escalations.append(POLICY_EXCEPTION)
            decision.tier = max(decision.tier, Tier.REVIEW)

        if decision.outcomes:
            decision.tier = max(decision.tier, max(o.tier for o in decision.outcomes))

        self._apply_budget(decision, profile)
        self.budget.record(profile.name, decision.tier >= Tier.ANNOTATE)
        return decision

    # -- internals ---------------------------------------------------------

    @staticmethod
    def _tier_for(
        signal: Signal, profile: Profile, low: float, high: float, exempt: set[str]
    ) -> tuple[Tier, str]:
        if exempt & set(signal.exemption_keys):
            # A reviewer has already judged this not worth flagging here.
            # Credentials can never reach this branch - the compiler refuses
            # to build a profile that exempts them.
            return Tier.ALLOW, "exempted by policy"

        if not signal.reversible:
            # Irreversible harm. Once it renders it is screen-recordable, so
            # there is no undo and the check has to be synchronous
            # (IDEATION section 6).
            if signal.confidence >= profile.decision.block_at:
                return Tier.BLOCK, "irreversible harm, high confidence"
            if low <= signal.confidence < high:
                return Tier.REVIEW, MID_BAND
            return Tier.ALLOW, "below threshold"

        if profile.decision.always_review:
            return Tier.REVIEW, PROFILE_RULE

        if signal.novel:
            # No prior means our confidence estimate is itself unreliable,
            # which is the one case where the number cannot be trusted.
            return Tier.REVIEW, NOVEL_PATTERN

        # NOTE: mid-band confidence does NOT escalate reversible harm.
        # Escalating the middle is the honest use of a reviewer only where the
        # harm cannot be undone. For a reversible finding we can simply show
        # the reader the evidence and let them judge - which is cheaper, adds
        # no safety a human would have added, and keeps the review queue for
        # decisions that actually need one. Sending every uncertain
        # hallucination flag to a person is how the queue becomes noise.
        if signal.confidence >= low:
            if signal.evidence:
                return Tier.ANNOTATE, "reversible harm, evidence available"
            # No flag without something actionable. "Possible issue" IS the
            # alert fatigue the brief warns about.
            return Tier.ALLOW, "no actionable evidence to show"

        return Tier.ALLOW, "below threshold"

    def _apply_budget(self, decision: Decision, profile: Profile) -> None:
        budget = profile.decision.flag_budget_per_100
        if decision.tier is Tier.BLOCK:
            # Irreversible harm is never rationed. A budget that could
            # suppress a credential block would be a fatigue feature that
            # silently disables the security control.
            return
        if decision.tier < Tier.ANNOTATE:
            return
        if not self.budget.would_exceed(profile.name, budget):
            return
        if profile.decision.always_review:
            # The profile said review everything; budget does not override it.
            return

        decision.suppressed = decision.user_visible_flags
        decision.sampled = True
        decision.tier = Tier.ALLOW


def signals_from_findings(findings, *, novel_categories: set[str] | None = None) -> list[Signal]:
    """Adapt engine findings into decision signals.

    Credentials and PII are irreversible: once rendered they are
    screen-recordable, and a leaked key is exploitable forever. Everything the
    substitution engine produces therefore arrives as `reversible=False`.
    Quality signals - hallucination, toxicity - come from a later phase and
    arrive reversible.
    """
    novel = novel_categories or set()
    return [
        Signal(
            category=f.category,
            kind=f.kind,
            confidence=f.confidence,
            reversible=False,
            record_ref=f.record_ref,
            evidence=(
                f"matched {f.record_ref}" if f.record_ref else f"matched {f.category} pattern"
            ),
            novel=f.category in novel,
        )
        for f in findings
    ]
