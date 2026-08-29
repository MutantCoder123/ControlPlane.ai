"""Session-level risk without session-level memory.

D4, escalated because the Round 2 brief names multi-turn and agentic
compounding risk directly. The point of these tests is that we catch the
compounding without storing a single prompt.
"""

import pytest

from controlplane.feedback.session import SessionRiskTracker


class _Finding:
    def __init__(self, record_ref):
        self.record_ref = record_ref


@pytest.fixture()
def tracker():
    return SessionRiskTracker(max_records_per_session=5, max_agent_steps=10)


def test_a_quiet_session_is_within_budget(tracker):
    verdict = tracker.observe("s1", findings=[_Finding("customer:1")])
    assert verdict and not verdict.over_budget


def test_cumulative_disclosure_trips_even_though_each_turn_looked_fine(tracker):
    """The compounding risk the brief describes, caught by counting.

    No single turn touches more than one record. Six turns in, the session
    has seen six distinct customers, which is worth stopping - and nothing
    about any individual request would have told us that.
    """
    for i in range(6):
        verdict = tracker.observe("s1", findings=[_Finding(f"customer:{i}")])
    assert verdict.over_budget
    assert "cumulative disclosure" in verdict.reasons[0]
    assert verdict.counters.distinct_records == 6


def test_the_same_record_repeatedly_is_not_sprawl(tracker):
    for _ in range(20):
        verdict = tracker.observe("s1", findings=[_Finding("customer:1")])
    assert not verdict.over_budget, "one customer, twenty turns, is normal support work"


def test_agent_step_budget(tracker):
    """IDEATION 12.1's agentic sprawl: one request quietly becoming forty."""
    verdict = tracker.observe("s1", agent_steps=11)
    assert verdict.over_budget and "agent sprawl" in verdict.reasons[0]


def test_sessions_are_independent(tracker):
    for i in range(6):
        tracker.observe("s1", findings=[_Finding(f"customer:{i}")])
    assert not tracker.observe("s2", findings=[_Finding("customer:99")]).over_budget


def test_tracker_holds_references_not_values(tracker):
    tracker.observe("s1", findings=[_Finding("customer:44219")])
    blob = repr(tracker.counters("s1"))
    assert "customer:44219" in blob
    assert "Priya" not in blob and "Sharma" not in blob


def test_there_is_nowhere_to_put_content(tracker):
    """The counters dataclass has no field that could hold a prompt.

    That is the architectural answer to D4: we track the aggregate, not the
    content, so multi-turn risk is visible without multi-turn memory.
    """
    from dataclasses import fields

    from controlplane.feedback.session import SessionCounters

    names = {f.name for f in fields(SessionCounters)}
    assert names == {
        "turns", "agent_steps", "findings", "blocks", "records_touched", "first_seen"
    }


def test_tracker_is_bounded():
    """A tracker that grows without limit is a memory leak in a governance costume."""
    tracker = SessionRiskTracker(max_sessions=10)
    for i in range(50):
        tracker.observe(f"s{i}")
    assert len(tracker) <= 10


def test_forget_drops_a_session(tracker):
    tracker.observe("s1")
    tracker.forget("s1")
    assert tracker.counters("s1") is None
