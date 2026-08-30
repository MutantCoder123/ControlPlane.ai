"""Canaries and the trust report.

D25 - the brief's hardest ask. The thing being tested is mostly HONESTY: that
a false-negative estimate cannot be quoted without its caveat, that there is
no single flattering score to put on a dial, and that what we did not measure
is named rather than omitted.
"""

from pathlib import Path

import pytest

from controlplane.cost.ledger import CostLedger
from controlplane.cost.pricing import Usage
from controlplane.decision.tiers import DecisionEngine, Signal
from controlplane.engine.substitute import SubstitutionEngine
from controlplane.metrics.canary import CanaryReport, CanarySuite
from controlplane.metrics.registry import MetricsRegistry
from controlplane.policy.store import ControlPlane

FIXTURE = str(Path(__file__).parents[1] / "test_engine" / "fixtures" / "records.jsonl")


@pytest.fixture(scope="module")
def engine():
    return SubstitutionEngine(FIXTURE)


@pytest.fixture()
def suite():
    return CanarySuite()


@pytest.fixture(scope="module")
def bundle():
    return ControlPlane().compile_bundle()


# --------------------------------------------------------------------------
# Canaries as the FN instrument
# --------------------------------------------------------------------------

def test_canaries_are_caught_by_the_real_engine(suite, engine):
    """The measurement has to run against the actual detector, not a mock."""
    canaries = suite.mint_batch({"payment_card": 6, "api_key": 4, "iban": 2})
    report = suite.run(canaries, engine.scan_inbound, profile="internal-knowledge")
    assert report.total == 12
    assert report.catch_rate > 0.9, f"missed: {[c.category for c in report.misses]}"


def test_catch_rate_and_miss_rate_are_complements(suite, engine):
    report = suite.run(suite.mint_batch({"payment_card": 4}), engine.scan_inbound)
    assert report.catch_rate + report.miss_rate == pytest.approx(1.0)


def test_the_caveat_travels_with_the_number(suite, engine):
    """A false-negative estimate that can be quoted bare is a lie waiting to
    happen. `__str__` cannot render the rate without the distribution.
    """
    report = suite.run(suite.mint_batch({"payment_card": 3, "api_key": 2}), engine.scan_inbound)
    text = str(report)
    assert "catch rate" in text
    assert "seeded distribution" in text
    assert "says nothing about categories we did not seed" in text


def test_confidence_interval_widens_on_a_small_sample(suite, engine):
    """Twelve canaries at 100% is not the same claim as twelve hundred."""
    small = suite.run(suite.mint_batch({"payment_card": 3}), engine.scan_inbound)
    large = suite.run(suite.mint_batch({"payment_card": 60}), engine.scan_inbound)
    small_width = small.confidence_interval[1] - small.confidence_interval[0]
    large_width = large.confidence_interval[1] - large.confidence_interval[0]
    assert small_width > large_width


def test_empty_report_does_not_claim_perfection():
    report = CanaryReport()
    assert report.catch_rate == 0.0
    assert report.confidence_interval == (0.0, 0.0)


def test_what_we_did_not_measure_is_named(suite, engine):
    """A report listing only what it measured invites the reader to assume
    it measured everything."""
    report = suite.run(suite.mint_batch({"payment_card": 2}), engine.scan_inbound)
    not_measured = " ".join(report.as_dict()["not_measured"])
    assert "dual-detector" in not_measured
    assert "downstream incident" in not_measured
    assert "unknown-unknowns" in not_measured


def test_per_category_breakdown_locates_a_blind_spot(suite, engine):
    report = suite.run(suite.mint_batch({"payment_card": 3, "aadhaar": 3}), engine.scan_inbound)
    assert set(report.by_category) == {"payment_card", "aadhaar"}
    for caught, total in report.by_category.values():
        assert total == 3


def test_canaries_are_deterministic():
    """Every number in the demo must reproduce from a clean checkout."""
    a = CanarySuite(seed=1).mint_batch({"payment_card": 5})
    b = CanarySuite(seed=1).mint_batch({"payment_card": 5})
    assert [c.value for c in a] == [c.value for c in b]


def test_unknown_canary_category_is_refused(suite):
    with pytest.raises(KeyError):
        suite.mint("something_we_have_no_template_for")


# --------------------------------------------------------------------------
# Per-profile metrics
# --------------------------------------------------------------------------

def test_metrics_are_per_profile_never_global(bundle):
    """A single FP figure across two profiles averages unrelated things."""
    registry = MetricsRegistry()
    engine = DecisionEngine()
    sig = Signal("customer_name", "known_value", 1.0, reversible=False)

    registry.record_decision(engine.decide([sig], bundle.get("customer-support")))
    registry.record_decision(engine.decide([], bundle.get("internal-knowledge")))

    report = registry.report()
    assert set(report.per_profile) == {"customer-support", "internal-knowledge"}
    assert "overall" not in report.as_dict()
    assert "trust_score" not in report.as_dict()


def test_flags_per_100_is_the_fatigue_metric(bundle):
    registry = MetricsRegistry()
    engine = DecisionEngine()
    sig = Signal("customer_name", "known_value", 1.0, reversible=False)
    for _ in range(4):
        registry.record_decision(engine.decide([sig], bundle.get("internal-knowledge")))
    for _ in range(6):
        registry.record_decision(engine.decide([], bundle.get("internal-knowledge")))
    assert registry.metrics_for("internal-knowledge").flags_per_100 == 40.0


def test_latency_percentiles(bundle):
    registry = MetricsRegistry()
    engine = DecisionEngine()
    for ms in range(1, 101):
        registry.record_decision(
            engine.decide([], bundle.get("internal-knowledge")), latency_ms=float(ms)
        )
    latency = registry.metrics_for("internal-knowledge").added_latency
    assert latency["p50"] < latency["p95"] < latency["p99"]


def test_there_is_no_single_trust_score(bundle):
    """Anyone can average six numbers onto a dial. The dial is exactly what a
    sceptical stakeholder should not accept, because it hides which input moved.
    """
    registry = MetricsRegistry()
    report = registry.report().as_dict()
    assert "no_single_score" in report["method"]
    assert "track record" in report["method"]["no_single_score"]


def test_method_states_the_fp_fn_asymmetry(bundle):
    method = MetricsRegistry().report().as_dict()["method"]
    assert "measured directly" in method["false_positives"]
    assert "ESTIMATED" in method["false_negatives"]
    assert "cannot count what we never detected" in method["false_negatives"]


# --------------------------------------------------------------------------
# The assembled report - what a sceptic actually sees
# --------------------------------------------------------------------------

def test_full_report_carries_override_rate_alongside_everything_else(bundle):
    """The number we look worst on, published on purpose."""
    from controlplane.feedback.loop import FeedbackAggregator, ReviewQueue, Verdict

    registry, engine = MetricsRegistry(), DecisionEngine()
    queue, aggregator = ReviewQueue(), FeedbackAggregator()

    mid = Signal("payment_card", "pattern", 0.7, reversible=False, evidence="x")
    for i in range(4):
        decision = engine.decide([mid], bundle.get("internal-knowledge"))
        registry.record_decision(decision, latency_ms=3.0)
        item = queue.enqueue_decision(decision, request_id=f"r{i}")[0]
        aggregator.observe(queue.resolve(item.item_id, Verdict.OVERRIDDEN, actor="anita"))

    ledger = CostLedger()
    ledger.record(request_id="r0", team="hr", profile="internal-knowledge",
                  usage=Usage("claude-haiku-4-5", input_tokens=10_000, output_tokens=500))

    report = registry.report(
        aggregator=aggregator,
        canary_report=CanarySuite().run(
            CanarySuite().mint_batch({"payment_card": 3}),
            SubstitutionEngine(FIXTURE).scan_inbound,
        ),
        savings=ledger.savings(),
    ).as_dict()

    profile = report["per_profile"]["internal-knowledge"]
    assert profile["override_rate"] == 1.0
    assert profile["false_positive_rate"] == 1.0
    assert report["canary"]["caveat"].startswith("This is a false-negative estimate")
    assert "net_saving_usd" in report["cost"]


# --------------------------------------------------------------------------
# The instrument has to be checked too
# --------------------------------------------------------------------------

@pytest.mark.parametrize(
    "category,value",
    [(c, v) for c, vs in CanarySuite.TEMPLATES.items() for v in vs],
)
def test_every_canary_template_is_catchable(engine, category, value):
    """A canary the detector could never catch measures nothing except our
    ability to write an impossible test.

    Regression: `AKIAIOSFODNN7CANARY` was 19 characters where a real AWS key
    id is 20, so it matched no pattern and silently pulled the reported catch
    rate down to 90%. The metric had a bug in the metric, and without this
    test we would have gone looking for a detector blind spot that did not
    exist.
    """
    findings = engine.scan_inbound(f"Please review this record: {value}.").findings
    assert findings, f"{category} canary {value!r} is not catchable by the engine"


def test_catch_rate_is_total_on_a_healthy_engine(suite, engine):
    """With well-formed canaries there is nowhere for a miss to hide."""
    report = suite.run(
        suite.mint_batch({"payment_card": 20, "api_key": 10, "iban": 6, "aadhaar": 6}),
        engine.scan_inbound,
    )
    assert report.catch_rate == 1.0, f"missed: {[(c.category, c.value) for c in report.misses]}"
