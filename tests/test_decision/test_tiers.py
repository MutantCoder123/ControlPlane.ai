"""Tiered decisions and escalation.

D26 and the brief's Decision Logic area. The rule under test throughout is
that the tier is a function of severity x confidence x profile - never the
finding alone. Without that, route profiles are decoration.
"""

import pytest

from controlplane.decision.tiers import (
    MID_BAND,
    NOVEL_PATTERN,
    POLICY_EXCEPTION,
    PROFILE_RULE,
    DecisionEngine,
    FlagBudget,
    Signal,
    Tier,
    signals_from_findings,
)
from controlplane.policy.profile import compile_profile
from controlplane.policy.store import ControlPlane


@pytest.fixture(scope="module")
def bundle():
    return ControlPlane().compile_bundle()


@pytest.fixture()
def engine():
    return DecisionEngine()


def irreversible(confidence=1.0, **kw):
    return Signal("customer_name", "known_value", confidence, reversible=False, **kw)


def reversible(confidence=0.95, evidence="varied across samples: 30 / 45 / 60 days", **kw):
    return Signal("hallucination", "quality", confidence, reversible=True, evidence=evidence, **kw)


# --------------------------------------------------------------------------
# The four tiers
# --------------------------------------------------------------------------

def test_no_signals_allows(engine, bundle):
    assert engine.decide([], bundle.get("internal-knowledge")).tier is Tier.ALLOW


def test_irreversible_and_confident_blocks(engine, bundle):
    d = engine.decide([irreversible(1.0)], bundle.get("internal-knowledge"))
    assert d.tier is Tier.BLOCK and d.blocked


def test_reversible_with_evidence_annotates(engine, bundle):
    d = engine.decide([reversible()], bundle.get("internal-knowledge"))
    assert d.tier is Tier.ANNOTATE


def test_mid_band_confidence_goes_to_a_human(engine, bundle):
    """The extremes are where automation is reliable. The middle is not."""
    d = engine.decide([irreversible(0.7)], bundle.get("internal-knowledge"))
    assert d.tier is Tier.REVIEW and d.needs_human
    assert MID_BAND in d.escalations


def test_strongest_signal_decides(engine, bundle):
    d = engine.decide(
        [reversible(), irreversible(1.0)], bundle.get("internal-knowledge")
    )
    assert d.tier is Tier.BLOCK


# --------------------------------------------------------------------------
# THE claim: same finding, different profile, different outcome
# --------------------------------------------------------------------------

def test_same_signal_resolves_differently_per_profile(engine, bundle):
    """What makes route profiles load-bearing rather than decorative."""
    signal = reversible(0.95)

    internal = engine.decide([signal], bundle.get("internal-knowledge"))
    decision_support = engine.decide([signal], bundle.get("decision-support"))

    assert internal.tier is Tier.ANNOTATE
    assert decision_support.tier is Tier.REVIEW
    assert PROFILE_RULE in decision_support.escalations


def test_decision_support_reviews_everything(engine, bundle):
    """IDEATION 12.2 - legal exposure justifies the cost of a human."""
    d = engine.decide([reversible(0.99)], bundle.get("decision-support"))
    assert d.tier is Tier.REVIEW


# --------------------------------------------------------------------------
# Escalation triggers (IDEATION 12.2)
# --------------------------------------------------------------------------

def test_novel_pattern_escalates_regardless_of_confidence(engine, bundle):
    """No prior means the confidence estimate is itself unreliable."""
    d = engine.decide([reversible(0.99, novel=True)], bundle.get("internal-knowledge"))
    assert d.tier is Tier.REVIEW and NOVEL_PATTERN in d.escalations


def test_policy_exception_escalates(engine, bundle):
    """D16: "validate this account number's checksum" is a human decision."""
    d = engine.decide([], bundle.get("internal-knowledge"), exception_requested=True)
    assert d.tier is Tier.REVIEW and POLICY_EXCEPTION in d.escalations


# --------------------------------------------------------------------------
# No flag without actionable evidence (IDEATION 12.3)
# --------------------------------------------------------------------------

def test_reversible_without_evidence_does_not_interrupt(engine, bundle):
    """"Possible issue" IS the alert fatigue the brief warns about."""
    d = engine.decide([reversible(0.99, evidence=None)], bundle.get("internal-knowledge"))
    assert d.tier is Tier.ALLOW
    assert d.outcomes[0].reason == "no actionable evidence to show"


# --------------------------------------------------------------------------
# Flag budget - over-flagging is tuned, not solved
# --------------------------------------------------------------------------

def test_budget_suppresses_flags_once_the_allowance_is_spent(bundle):
    engine = DecisionEngine(FlagBudget(window=100))
    profile = bundle.get("customer-support")      # flag_budget_per_100 = 5

    for _ in range(100):
        engine.decide([reversible()], profile)

    d = engine.decide([reversible()], profile)
    assert d.tier is Tier.ALLOW
    assert d.suppressed and d.sampled, "suppressed flags are still sampled for measurement"


def test_budget_never_suppresses_a_block(bundle):
    """A fatigue feature that can silence a credential block is a bug.

    Irreversible harm is not rationed - otherwise the budget becomes a way to
    switch off the security control by being noisy first.
    """
    engine = DecisionEngine(FlagBudget(window=100))
    profile = bundle.get("customer-support")
    for _ in range(100):
        engine.decide([reversible()], profile)

    d = engine.decide([irreversible(1.0)], profile)
    assert d.tier is Tier.BLOCK and not d.sampled


def test_budget_does_not_throttle_on_a_thin_sample(bundle):
    """Under-flagging creates real liability, so we do not judge early."""
    engine = DecisionEngine(FlagBudget(window=100))
    profile = bundle.get("customer-support")
    for _ in range(5):
        d = engine.decide([reversible()], profile)
    assert d.tier is Tier.ANNOTATE


def test_budget_does_not_override_always_review(bundle):
    engine = DecisionEngine(FlagBudget(window=100))
    profile = bundle.get("decision-support")
    for _ in range(120):
        d = engine.decide([reversible()], profile)
    assert d.tier is Tier.REVIEW


def test_budget_holds_no_content():
    """Statelessness check (IDEATION section 3).

    The window is a fixed-length deque of booleans. There is nowhere in it to
    put a prompt, a value, or a user - which is what makes it "aggregate
    statistics about decisions" rather than retained state.
    """
    budget = FlagBudget(window=10)
    for _ in range(10):
        budget.record("p", True)
    blob = repr(budget._window)
    assert "True" in blob
    assert all(isinstance(v, bool) for v in budget._window["p"])
    assert budget.rate_per_100("p") == 100.0


# --------------------------------------------------------------------------
# Exemptions
# --------------------------------------------------------------------------

def test_exempted_category_is_allowed(engine):
    profile = compile_profile(
        {"name": "p", "decision": {"exempt": ["pattern:payment_card"]}}
    )
    signal = Signal("payment_card", "pattern", 0.9, reversible=False)
    d = engine.decide([signal], profile)
    assert d.tier is Tier.ALLOW
    assert d.outcomes[0].reason == "exempted by policy"


def test_credentials_can_never_be_exempted():
    """A reviewer must not be able to switch off irreversible-harm blocking
    one override at a time."""
    from controlplane.policy.profile import PolicyError

    with pytest.raises(PolicyError, match="credentials cannot be exempted"):
        compile_profile({"name": "p", "decision": {"exempt": ["pattern:api_key"]}})


# --------------------------------------------------------------------------
# Adapting engine findings
# --------------------------------------------------------------------------

def test_engine_findings_are_irreversible(engine, bundle):
    """A leaked key is exploitable forever; a rendered name is screen-recorded."""
    from pathlib import Path

    from controlplane.engine.substitute import SubstitutionEngine

    fixture = str(Path(__file__).parents[1] / "test_engine" / "fixtures" / "records.jsonl")
    scanned = SubstitutionEngine(fixture).scan_inbound("Refund Priya Sharma.")

    signals = signals_from_findings(scanned.findings)
    assert signals and all(not s.reversible for s in signals)
    assert signals[0].record_ref == "customer:44219"
    assert "customer:44219" in signals[0].evidence


def test_audit_payload_carries_references_not_values(engine, bundle):
    d = engine.decide([irreversible(1.0, record_ref="customer:44219")], bundle.get("internal-knowledge"))
    payload = d.audit_payload()
    assert payload["signals"][0]["record_ref"] == "customer:44219"
    assert "Priya" not in repr(payload)
    assert payload["tier"] == "block"


def test_public_facing_blocks_on_evidence_that_only_reviews_internally(engine, bundle):
    """The same finding, the same confidence, two different outcomes.

    Customer-facing output reaches the public: a wrong answer becomes a
    commitment the organisation has to honour, and a leak is seen by someone
    outside it. The same evidence therefore justifies stopping earlier there
    than on an internal assistant.

    This is the clearest demonstration that the tier is a function of
    severity x confidence x PROFILE.
    """
    signal = irreversible(0.8)
    assert engine.decide([signal], bundle.get("customer-support")).tier is Tier.BLOCK
    assert engine.decide([signal], bundle.get("internal-knowledge")).tier is Tier.REVIEW


def test_thresholds_actually_differ_across_profiles(bundle):
    thresholds = {n: bundle.get(n).decision.block_at for n in bundle.names}
    assert len(set(thresholds.values())) == 3, thresholds


def test_mid_band_does_not_escalate_reversible_harm(engine, bundle):
    """Escalating the middle is the honest use of a reviewer only where the
    harm cannot be undone.

    For a reversible finding we can show the reader the evidence and let them
    judge - cheaper, adds no safety a human would have added, and keeps the
    review queue for decisions that actually need one. Sending every uncertain
    hallucination flag to a person is how the queue becomes noise, which is
    the alert fatigue the brief warns about arriving by a different door.
    """
    mid = 0.65
    low, high = bundle.get("internal-knowledge").decision.review_band
    assert low <= mid < high

    rev = Signal("hallucination", "quality", mid, reversible=True, evidence="check 30/45/60")
    irr = Signal("customer_name", "known_value", mid, reversible=False)

    assert engine.decide([rev], bundle.get("internal-knowledge")).tier is Tier.ANNOTATE
    assert engine.decide([irr], bundle.get("internal-knowledge")).tier is Tier.REVIEW
