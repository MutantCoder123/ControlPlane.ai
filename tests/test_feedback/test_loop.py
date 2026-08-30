"""The feedback loop, and the statelessness constraint it has to respect.

D24. The claim under test is IDEATION section 13.1: the data plane stays
stateless, the control plane learns. If the queue or the aggregator can be
shown to hold conversation content, the resolution fails and section 3 goes
with it.
"""

import pytest

from controlplane.audit.chain import AuditLog, attach_to_store
from controlplane.decision.tiers import DecisionEngine, Signal, Tier
from controlplane.feedback.loop import (
    FeedbackAggregator,
    PolicyTuner,
    ReviewQueue,
    Verdict,
    close_loop,
)
from controlplane.policy.store import ControlPlane


@pytest.fixture()
def control():
    return ControlPlane()


@pytest.fixture()
def store(control):
    return control.store(default_profile="internal-knowledge")


@pytest.fixture()
def engine():
    return DecisionEngine()


def mid_band(category="payment_card", kind="pattern"):
    """Confidence 0.7 lands in the default review band, so it reaches a human."""
    return Signal(category, kind, 0.7, reversible=False, evidence=f"matched {category}")


# --------------------------------------------------------------------------
# Queue
# --------------------------------------------------------------------------

def test_review_tier_reaches_the_queue(engine, store):
    queue = ReviewQueue()
    decision = engine.decide([mid_band()], store.profile_for("internal-knowledge"))
    assert decision.tier is Tier.REVIEW

    items = queue.enqueue_decision(decision, request_id="req-1")
    assert len(items) == 1 and len(queue) == 1
    assert items[0].category == "payment_card"


def test_allowed_decisions_do_not_queue(engine, store):
    queue = ReviewQueue()
    queue.enqueue_decision(engine.decide([], store.profile_for("internal-knowledge")))
    assert len(queue) == 0


def test_resolving_removes_from_pending(engine, store):
    queue = ReviewQueue()
    item = queue.enqueue_decision(engine.decide([mid_band()], store.profile_for("internal-knowledge")))[0]
    queue.resolve(item.item_id, Verdict.OVERRIDDEN, actor="anita")
    assert len(queue) == 0 and len(queue.resolved) == 1


def test_resolving_an_unknown_item_errors(engine):
    with pytest.raises(KeyError):
        ReviewQueue().resolve("nope", Verdict.CONFIRMED, actor="anita")


# --------------------------------------------------------------------------
# The statelessness constraint - this is the load-bearing test
# --------------------------------------------------------------------------

def test_the_queue_holds_no_conversation_content(engine, store):
    """IDEATION 13.1. Feedback is aggregate statistics ABOUT DECISIONS.

    If a prompt or a matched value could reach the review queue, the loop
    would have quietly reintroduced exactly the concentration risk section 3
    exists to avoid.
    """
    from pathlib import Path

    from controlplane.engine.substitute import SubstitutionEngine
    from controlplane.decision.tiers import signals_from_findings

    fixture = str(Path(__file__).parents[1] / "test_engine" / "fixtures" / "records.jsonl")
    prompt = "Refund Priya Sharma on account 50100234567890."
    scanned = SubstitutionEngine(fixture).scan_inbound(prompt)

    queue = ReviewQueue()
    signals = [Signal(s.category, s.kind, 0.7, reversible=False, record_ref=s.record_ref)
               for s in signals_from_findings(scanned.findings)]
    queue.enqueue_decision(
        engine.decide(signals, store.profile_for("internal-knowledge")), request_id="r1"
    )

    blob = repr(queue.pending)
    assert "customer:44219" in blob            # the reference survives
    for secret in ("Priya", "Sharma", "50100234567890", "Refund"):
        assert secret not in blob              # the content does not


def test_the_aggregator_holds_only_counts(engine, store):
    queue = ReviewQueue()
    aggregator = FeedbackAggregator()
    for i in range(3):
        item = queue.enqueue_decision(
            engine.decide([mid_band()], store.profile_for("internal-knowledge")), request_id=f"r{i}"
        )[0]
        aggregator.observe(queue.resolve(item.item_id, Verdict.OVERRIDDEN, actor="anita"))

    stats = aggregator.stats_for("internal-knowledge", "pattern", "payment_card")
    assert stats.overridden == 3 and stats.confirmed == 0
    assert stats.override_rate == 1.0


def test_override_rate_is_reportable(engine, store):
    """The metric we look worst on, published on purpose (IDEATION 14.3)."""
    queue, aggregator = ReviewQueue(), FeedbackAggregator()
    verdicts = [Verdict.OVERRIDDEN, Verdict.OVERRIDDEN, Verdict.CONFIRMED, Verdict.CONFIRMED]
    for i, verdict in enumerate(verdicts):
        item = queue.enqueue_decision(
            engine.decide([mid_band()], store.profile_for("internal-knowledge")), request_id=f"r{i}"
        )[0]
        aggregator.observe(queue.resolve(item.item_id, verdict, actor="anita"))
    assert aggregator.override_rate() == 0.5


def test_unclear_verdicts_count_for_neither(engine, store):
    """Genuinely ambiguous cases must not be scored as our failure or success."""
    queue, aggregator = ReviewQueue(), FeedbackAggregator()
    for i in range(3):
        item = queue.enqueue_decision(
            engine.decide([mid_band()], store.profile_for("internal-knowledge")), request_id=f"r{i}"
        )[0]
        aggregator.observe(queue.resolve(item.item_id, Verdict.UNCLEAR, actor="anita"))
    assert aggregator.override_rate() == 0.0
    assert aggregator.stats_for("internal-knowledge", "pattern", "payment_card").unclear == 3


# --------------------------------------------------------------------------
# Tuning - thresholds and exception lists, never model weights
# --------------------------------------------------------------------------

def _override_n(engine, store, queue, aggregator, n, category="payment_card"):
    for i in range(n):
        item = queue.enqueue_decision(
            engine.decide([mid_band(category)], store.profile_for("internal-knowledge")),
            request_id=f"r{i}",
        )[0]
        aggregator.observe(queue.resolve(item.item_id, Verdict.OVERRIDDEN, actor="anita"))


def test_one_annoyed_reviewer_changes_nothing(engine, store):
    """Deliberately conservative: a hole in the detector needs evidence."""
    queue, aggregator = ReviewQueue(), FeedbackAggregator()
    _override_n(engine, store, queue, aggregator, 2)
    assert PolicyTuner(aggregator).propose(store.bundle) == []


def test_repeated_overrides_propose_an_exemption(engine, store):
    queue, aggregator = ReviewQueue(), FeedbackAggregator()
    _override_n(engine, store, queue, aggregator, 4)

    proposals = PolicyTuner(aggregator).propose(store.bundle)
    assert len(proposals) == 1
    assert proposals[0].path == "decision.exempt"
    assert "pattern:payment_card" in proposals[0].proposed
    assert proposals[0].sample_size == 4
    assert "4 of 4 reviews overturned" in proposals[0].rationale


def test_credentials_are_never_proposed_for_exemption(engine, store):
    """Not tunable, and the reviewer gets an explanation rather than a
    compile error."""
    queue, aggregator = ReviewQueue(), FeedbackAggregator()
    _override_n(engine, store, queue, aggregator, 5, category="api_key")
    assert PolicyTuner(aggregator).propose(store.bundle) == []


def test_confirmed_findings_propose_nothing(engine, store):
    queue, aggregator = ReviewQueue(), FeedbackAggregator()
    for i in range(5):
        item = queue.enqueue_decision(
            engine.decide([mid_band()], store.profile_for("internal-knowledge")), request_id=f"r{i}"
        )[0]
        aggregator.observe(queue.resolve(item.item_id, Verdict.CONFIRMED, actor="anita"))
    assert PolicyTuner(aggregator).propose(store.bundle) == []


# --------------------------------------------------------------------------
# Closing the loop - the whole point
# --------------------------------------------------------------------------

def test_an_override_changes_the_next_identical_decision(engine, control, store):
    """detection -> review -> override -> aggregate -> new policy -> different result.

    This is the incident->action loop IDEATION section 23 asks for, and the
    difference between a tool that reports and a tool that improves.
    """
    queue, aggregator = ReviewQueue(), FeedbackAggregator()

    before = engine.decide([mid_band()], store.profile_for("internal-knowledge"))
    assert before.tier is Tier.REVIEW

    _override_n(engine, store, queue, aggregator, 4)
    applied = close_loop(aggregator=aggregator, control_plane=control, store=store)
    assert applied

    after = engine.decide([mid_band()], store.profile_for("internal-knowledge"))
    assert after.tier is Tier.ALLOW
    assert after.outcomes[0].reason == "exempted by policy"


def test_the_change_is_auditable_and_readable(engine, control, store):
    """A customer must be able to read WHY a decision changed.

    "The model learned" is not an answer a regulator accepts (IDEATION 13.3).
    """
    log = AuditLog()
    attach_to_store(log, store)
    queue, aggregator = ReviewQueue(), FeedbackAggregator()

    _override_n(engine, store, queue, aggregator, 4)
    close_loop(aggregator=aggregator, control_plane=control, store=store, audit_log=log)

    applied = log.by_event("feedback_applied")
    assert len(applied) == 1
    assert "4 of 4 reviews overturned" in applied[0].payload["proposals"][0]["rationale"]

    change = log.by_event("policy_change")[-1]
    diff = change.payload["changes"]["internal-knowledge"]
    assert "decision.exempt" in diff
    assert log.verify()


def test_closing_the_loop_with_no_evidence_is_a_no_op(control, store):
    before = store.version
    assert close_loop(aggregator=FeedbackAggregator(), control_plane=control, store=store) == []
    assert store.version == before


def test_loop_does_not_retrain_anything(engine, control, store):
    """We tune thresholds and exception lists - inspectable, diffable,
    revertible values. Nothing here touches a model."""
    queue, aggregator = ReviewQueue(), FeedbackAggregator()
    _override_n(engine, store, queue, aggregator, 4)
    proposals = close_loop(aggregator=aggregator, control_plane=control, store=store)

    assert all(p.path.startswith("decision.") for p in proposals)
    # and the result is a readable policy value, not an opaque weight
    assert store.profile_for("internal-knowledge").decision.exempt == ("pattern:payment_card",)
