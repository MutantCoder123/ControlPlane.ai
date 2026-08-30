"""Metrics - what we report to a sceptic, and how we avoid flattering ourselves.

D25, IDEATION section 14.2/14.3.

REPORTED PER PROFILE, NEVER GLOBALLY
------------------------------------
A single FP number spanning `customer-support` and `internal-knowledge` is an
average of two unrelated things. `TrustReport` therefore has no global
aggregate to ask for - the API shape enforces the rule rather than
documenting it.

THE POSTURE THAT MAKES IT CREDIBLE
----------------------------------
Report the override rate prominently. A governance tool that hides how often
it is wrong is asking for the trust it claims to provide, and publishing the
number we look worst on is what makes the others believable.

    Trustworthiness is not a score. It is a track record.

So there is no single "trust score" here, deliberately. Anyone can compute a
weighted average of six numbers and put it on a dial; the dial is exactly the
artefact a sceptical stakeholder should not accept, because it hides which
input moved.
"""

from __future__ import annotations

import statistics
from collections import defaultdict
from dataclasses import dataclass, field


@dataclass
class ProfileMetrics:
    """Everything we know about how one profile is behaving."""

    profile: str
    decisions: int = 0
    flags: int = 0                  # annotate or above, user-visible
    blocks: int = 0
    reviews: int = 0
    suppressed: int = 0             # withheld by the flag budget
    latencies_ms: list[float] = field(default_factory=list)

    @property
    def flags_per_100(self) -> float:
        """The alert-fatigue metric (IDEATION 12.3)."""
        return 100.0 * self.flags / self.decisions if self.decisions else 0.0

    @property
    def block_rate(self) -> float:
        return self.blocks / self.decisions if self.decisions else 0.0

    def latency(self, pct: float) -> float:
        if not self.latencies_ms:
            return 0.0
        ordered = sorted(self.latencies_ms)
        idx = min(len(ordered) - 1, int(round(pct / 100 * (len(ordered) - 1))))
        return ordered[idx]

    @property
    def added_latency(self) -> dict[str, float]:
        return {
            "p50": round(self.latency(50), 2),
            "p95": round(self.latency(95), 2),
            "p99": round(self.latency(99), 2),
        }


@dataclass
class TrustReport:
    """Per-profile only. There is deliberately no global score to quote."""

    per_profile: dict[str, dict] = field(default_factory=dict)
    canary: dict | None = None
    cost: dict | None = None
    method: dict = field(default_factory=dict)

    def as_dict(self) -> dict:
        return {
            "per_profile": self.per_profile,
            "canary": self.canary,
            "cost": self.cost,
            "method": self.method,
        }


class MetricsRegistry:
    """Counters and latencies per profile. No content, as everywhere else."""

    def __init__(self) -> None:
        self._profiles: dict[str, ProfileMetrics] = {}

    def _for(self, profile: str) -> ProfileMetrics:
        return self._profiles.setdefault(profile, ProfileMetrics(profile=profile))

    def record_decision(self, decision, *, latency_ms: float | None = None) -> None:
        metrics = self._for(decision.profile or "unknown")
        metrics.decisions += 1
        metrics.suppressed += decision.suppressed
        if latency_ms is not None:
            metrics.latencies_ms.append(latency_ms)

        tier = decision.tier.label
        if tier == "block":
            metrics.blocks += 1
            metrics.flags += 1
        elif tier == "review":
            metrics.reviews += 1
            metrics.flags += 1
        elif tier == "annotate":
            metrics.flags += 1

    def profiles(self) -> list[str]:
        return sorted(self._profiles)

    def metrics_for(self, profile: str) -> ProfileMetrics:
        return self._for(profile)

    def report(
        self,
        *,
        aggregator=None,
        canary_report=None,
        savings=None,
    ) -> TrustReport:
        """Assemble what we would actually show a sceptical stakeholder."""
        per_profile: dict[str, dict] = {}
        for name, metrics in sorted(self._profiles.items()):
            entry = {
                "decisions": metrics.decisions,
                "flags_per_100": round(metrics.flags_per_100, 2),
                "blocks": metrics.blocks,
                "reviews": metrics.reviews,
                "suppressed_by_budget": metrics.suppressed,
                "added_latency_ms": metrics.added_latency,
            }
            if aggregator is not None:
                # The number we look worst on, first in the block on purpose.
                entry["override_rate"] = round(aggregator.override_rate(name), 4)
                entry["false_positive_rate"] = entry["override_rate"]
            per_profile[name] = entry

        return TrustReport(
            per_profile=per_profile,
            canary=canary_report.as_dict() if canary_report is not None else None,
            cost=savings.as_dict() if savings is not None else None,
            method={
                "false_positives": (
                    "measured directly - every block and flag can be shown to a "
                    "reviewer, and disagreement is a false positive"
                ),
                "false_negatives": (
                    "ESTIMATED from seeded canaries. We cannot count what we never "
                    "detected; the same gap that causes a miss hides it. Any precise "
                    "FN rate is a number nobody can have."
                ),
                "aggregation": (
                    "per profile only - a single figure across customer-support and "
                    "internal-knowledge averages two unrelated things"
                ),
                "no_single_score": (
                    "trustworthiness is a track record, not a dial. A weighted "
                    "average would hide which input moved."
                ),
            },
        )
