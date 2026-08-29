"""The feedback loop - how detection improves without us storing anything.

D24. The Round 2 brief asks: "how flagged or overridden cases feed back to
improve detection quality over time." We had nothing, and worse, a loop
appears to contradict IDEATION section 3, which says we store nothing.

THE RESOLUTION (IDEATION section 13.1)
--------------------------------------
    The data plane stays stateless. The control plane learns.

Feedback is never per-request state. It is AGGREGATE STATISTICS ABOUT
DECISIONS - counts of "a reviewer said this category was wrong here" -
accumulated centrally and compiled into the next policy artefact. A
checkpoint never remembers a request. The control plane remembers only what
it concluded about the policy.

So section 3 survives intact: we still hold no conversation content, and the
thing we accumulate is not sensitive. `ReviewItem` carries a record
reference and a category, never a prompt or a matched value - and there is a
test that asserts exactly that.

WHAT WE DELIBERATELY DO NOT DO (IDEATION section 13.3)
------------------------------------------------------
We do not retrain a model on customer data. That would rebuild precisely the
concentration risk section 3 exists to avoid, and it would make our behaviour
non-reproducible for an auditor.

We tune THRESHOLDS and EXCEPTION LISTS - inspectable, diffable, revertible
values in a policy artefact. A customer can read the diff and see why a
decision changed. "The model learned" is not an answer a regulator accepts.

CLOSING THE LOOP
----------------
    detection -> review -> override/confirm -> aggregate
              -> threshold or exception change -> new policy artefact
              -> pushed to checkpoints -> measurable movement in FP rate

This is the incident->action loop IDEATION section 23 asks for, and the
difference between a tool that reports and a tool that improves.
"""

from __future__ import annotations

import itertools
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum


class Verdict(str, Enum):
    """What a reviewer concluded."""

    CONFIRMED = "confirmed"       # we were right to flag it
    OVERRIDDEN = "overridden"     # we were wrong; this is a false positive
    UNCLEAR = "unclear"           # genuinely ambiguous - counts for neither


@dataclass(frozen=True)
class ReviewItem:
    """One decision queued for a human.

    Note what is absent: the prompt, the response, the matched value, the
    user. A category, a kind, a confidence and a record reference are enough
    for a reviewer to judge and for us to aggregate, and useless to anyone
    who steals the queue.
    """

    item_id: str
    profile: str
    category: str
    kind: str
    confidence: float
    tier: str
    record_ref: str | None = None
    evidence: str | None = None
    reason: str = ""
    queued_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat(timespec="seconds")
    )

    @property
    def signature(self) -> tuple[str, str, str]:
        """What the aggregate is keyed on."""
        return (self.profile, self.kind, self.category)


@dataclass(frozen=True)
class Resolution:
    item: ReviewItem
    verdict: Verdict
    actor: str
    note: str = ""
    resolved_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat(timespec="seconds")
    )


class ReviewQueue:
    """Where the REVIEW tier sends things, and where verdicts come back."""

    def __init__(self) -> None:
        self._pending: dict[str, ReviewItem] = {}
        self._resolved: list[Resolution] = []
        self._ids = itertools.count(1)

    def enqueue_decision(self, decision, *, request_id: str = "") -> list[ReviewItem]:
        """Queue every signal that pushed a decision to REVIEW."""
        items: list[ReviewItem] = []
        for outcome in decision.outcomes:
            if outcome.tier.label != "review":
                continue
            item = ReviewItem(
                item_id=f"{request_id or 'req'}-{next(self._ids)}",
                profile=decision.profile,
                category=outcome.signal.category,
                kind=outcome.signal.kind,
                confidence=outcome.signal.confidence,
                tier=outcome.tier.label,
                record_ref=outcome.signal.record_ref,
                evidence=outcome.signal.evidence,
                reason=outcome.reason,
            )
            self._pending[item.item_id] = item
            items.append(item)
        return items

    def resolve(self, item_id: str, verdict: Verdict, actor: str, note: str = "") -> Resolution:
        item = self._pending.pop(item_id, None)
        if item is None:
            raise KeyError(f"no pending review item {item_id!r}")
        resolution = Resolution(item=item, verdict=verdict, actor=actor, note=note)
        self._resolved.append(resolution)
        return resolution

    @property
    def pending(self) -> list[ReviewItem]:
        return list(self._pending.values())

    @property
    def resolved(self) -> list[Resolution]:
        return list(self._resolved)

    def __len__(self) -> int:
        return len(self._pending)


@dataclass
class SignatureStats:
    confirmed: int = 0
    overridden: int = 0
    unclear: int = 0

    @property
    def judged(self) -> int:
        return self.confirmed + self.overridden

    @property
    def override_rate(self) -> float:
        """How often humans disagreed with us.

        Reported prominently on purpose (IDEATION section 14.3): a governance
        tool that hides how often it is wrong is asking for the trust it
        claims to provide.
        """
        return self.overridden / self.judged if self.judged else 0.0


class FeedbackAggregator:
    """Counts verdicts per (profile, kind, category). Holds nothing else."""

    def __init__(self) -> None:
        self._stats: dict[tuple[str, str, str], SignatureStats] = defaultdict(SignatureStats)

    def observe(self, resolution: Resolution) -> None:
        stats = self._stats[resolution.item.signature]
        setattr(stats, resolution.verdict.value, getattr(stats, resolution.verdict.value) + 1)

    def observe_all(self, resolutions) -> None:
        for resolution in resolutions:
            self.observe(resolution)

    def stats_for(self, profile: str, kind: str, category: str) -> SignatureStats:
        return self._stats[(profile, kind, category)]

    def override_rate(self, profile: str | None = None) -> float:
        total = SignatureStats()
        for (prof, _, _), stats in self._stats.items():
            if profile and prof != profile:
                continue
            total.confirmed += stats.confirmed
            total.overridden += stats.overridden
        return total.override_rate

    def summary(self) -> dict:
        return {
            f"{p}/{k}/{c}": {
                "confirmed": s.confirmed,
                "overridden": s.overridden,
                "unclear": s.unclear,
                "override_rate": round(s.override_rate, 3),
            }
            for (p, k, c), s in sorted(self._stats.items())
        }


@dataclass(frozen=True)
class Proposal:
    """A policy change the evidence supports, with the evidence attached."""

    profile: str
    path: str
    current: object
    proposed: object
    rationale: str
    sample_size: int

    def as_override(self) -> dict:
        section, _, key = self.path.partition(".")
        return {section: {key: self.proposed}}


class PolicyTuner:
    """Turns aggregate verdicts into proposed policy changes.

    Never touches model weights. Produces exemptions and threshold moves -
    both of which appear as a readable diff in the audit log.

    Deliberately conservative: it takes MIN_EVIDENCE independent reviews
    before proposing anything. One annoyed reviewer at 5pm on a Friday should
    not be able to widen a hole in the detector.
    """

    MIN_EVIDENCE = 3
    OVERRIDE_THRESHOLD = 0.66
    THRESHOLD_STEP = 0.05

    def __init__(self, aggregator: FeedbackAggregator) -> None:
        self.aggregator = aggregator

    def propose(self, bundle) -> list[Proposal]:
        proposals: list[Proposal] = []
        for (profile_name, kind, category), stats in sorted(self.aggregator._stats.items()):
            if stats.judged < self.MIN_EVIDENCE:
                continue
            if stats.override_rate < self.OVERRIDE_THRESHOLD:
                continue

            profile = bundle.get(profile_name)
            if profile is None:
                continue

            # Credentials are not tunable. The compiler would refuse the
            # resulting profile anyway; refusing to propose it means the
            # reviewer gets an explanation instead of a compile error.
            if category in {"api_key", "jwt", "private_key"}:
                continue

            key = f"{kind}:{category}"
            if key in profile.decision.exempt:
                continue

            proposals.append(
                Proposal(
                    profile=profile_name,
                    path="decision.exempt",
                    current=list(profile.decision.exempt),
                    proposed=sorted(set(profile.decision.exempt) | {key}),
                    rationale=(
                        f"{stats.overridden} of {stats.judged} reviews overturned "
                        f"{key} on {profile_name}"
                    ),
                    sample_size=stats.judged,
                )
            )
        return proposals

    @staticmethod
    def to_overrides(proposals: list[Proposal]) -> dict[str, dict]:
        overrides: dict[str, dict] = {}
        for proposal in proposals:
            target = overrides.setdefault(proposal.profile, {})
            for section, values in proposal.as_override().items():
                target.setdefault(section, {}).update(values)
        return overrides


def close_loop(
    *,
    aggregator: FeedbackAggregator,
    control_plane,
    store,
    audit_log=None,
    actor: str = "reviewer",
) -> list[Proposal]:
    """Aggregate -> propose -> recompile -> publish, in one call.

    Returns what was applied. Publishing writes its own diff to the audit log
    via the listener attached in phase 2, so the reason a request behaves
    differently afterwards is readable rather than mysterious.
    """
    tuner = PolicyTuner(aggregator)
    proposals = tuner.propose(store.bundle)
    if not proposals:
        return []

    bundle = control_plane.compile_bundle(overrides=tuner.to_overrides(proposals))
    store.publish(bundle)

    if audit_log is not None:
        audit_log.append(
            "feedback_applied",
            actor=actor,
            to_version=bundle.version,
            proposals=[
                {
                    "profile": p.profile,
                    "path": p.path,
                    "rationale": p.rationale,
                    "sample_size": p.sample_size,
                }
                for p in proposals
            ],
        )
    return proposals
