"""Session-level risk, without session-level memory.

D4, escalated after the Round 2 brief named it directly: "multi-turn
conversations and AI agents that take actions (not just generate text)
introduce compounding risk, where one questionable output can shape several
downstream decisions."

IDEATION section 22 lists "no multi-turn conversation state" as a limitation,
and we are not abandoning statelessness to fix it - that would trade our
entire positioning for one feature.

THE ARCHITECTURAL ANSWER
------------------------
Per-request checking stays stateless. Conversation-level and agent-level risk
becomes a CONTROL-PLANE concern, and it is answered with COUNTERS rather than
CONTENT:

    - how many turns has this session had
    - how many distinct records have been disclosed across them
    - how many steps has this agent taken

None of that requires remembering what was said. A session that has touched
forty distinct customer records is worth stopping regardless of whether any
single turn looked alarming - and that is precisely the compounding risk the
brief describes, caught without storing a single prompt.

WHAT THIS IS NOT
----------------
It is not multi-turn analysis. We cannot tell you that turn 3 contradicted
turn 1, because we did not keep turn 1. Full conversational reasoning is out
of prototype scope and stated as such. What we have is the aggregate, which
is the half that can be done without becoming the thing we protect against.

The session id is supplied by the customer's application. We never mint one,
because minting one would make us able to correlate traffic we have no
business correlating.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone


@dataclass
class SessionCounters:
    """Counts only. There is deliberately nowhere here to put content."""

    turns: int = 0
    agent_steps: int = 0
    findings: int = 0
    blocks: int = 0
    #: Record REFERENCES, not values - "customer:44219", never "Priya Sharma".
    #: A reference is a pointer into a system that already holds the data
    #: under its own controls (IDEATION section 18).
    records_touched: set[str] = field(default_factory=set)
    first_seen: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat(timespec="seconds")
    )

    @property
    def distinct_records(self) -> int:
        return len(self.records_touched)


@dataclass(frozen=True)
class SessionVerdict:
    over_budget: bool
    reasons: list[str]
    counters: SessionCounters

    def __bool__(self) -> bool:
        return not self.over_budget


class SessionRiskTracker:
    """Cumulative disclosure and step budgets, keyed by a customer-supplied id.

    Bounded on purpose: a tracker that grows without limit is a memory leak
    wearing a governance costume.
    """

    def __init__(
        self,
        *,
        max_records_per_session: int = 25,
        max_agent_steps: int = 40,
        max_sessions: int = 10_000,
    ) -> None:
        self.max_records = max_records_per_session
        self.max_steps = max_agent_steps
        self.max_sessions = max_sessions
        self._sessions: dict[str, SessionCounters] = {}

    def observe(
        self,
        session_id: str,
        *,
        findings=(),
        blocked: bool = False,
        agent_steps: int = 0,
    ) -> SessionVerdict:
        """Fold one request's outcome into the session's counters."""
        counters = self._sessions.get(session_id)
        if counters is None:
            if len(self._sessions) >= self.max_sessions:
                self._evict_oldest()
            counters = SessionCounters()
            self._sessions[session_id] = counters

        counters.turns += 1
        counters.agent_steps += agent_steps
        counters.findings += len(findings)
        counters.blocks += int(blocked)
        for finding in findings:
            ref = getattr(finding, "record_ref", None)
            if ref:
                counters.records_touched.add(ref)

        reasons: list[str] = []
        if counters.distinct_records > self.max_records:
            reasons.append(
                f"cumulative disclosure: {counters.distinct_records} distinct records "
                f"across {counters.turns} turns (limit {self.max_records})"
            )
        if counters.agent_steps > self.max_steps:
            reasons.append(
                f"agent sprawl: {counters.agent_steps} steps (limit {self.max_steps})"
            )
        return SessionVerdict(bool(reasons), reasons, counters)

    def counters(self, session_id: str) -> SessionCounters | None:
        return self._sessions.get(session_id)

    def forget(self, session_id: str) -> None:
        self._sessions.pop(session_id, None)

    def _evict_oldest(self) -> None:
        oldest = min(self._sessions, key=lambda s: self._sessions[s].first_seen)
        del self._sessions[oldest]

    def __len__(self) -> int:
        return len(self._sessions)
