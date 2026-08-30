"""Async quality checks - the reversible half.

Two things are being tested: that the checks we DID build work, and that the
ones we did not build are honestly labelled rather than quietly returning
empty (D23).
"""

import pytest

from controlplane.decision.tiers import DecisionEngine, Tier
from controlplane.policy.store import ControlPlane
from controlplane.quality.checks import (
    CounterfactualProbe,
    OutcomeDistribution,
    consistency_sample,
    entity_not_in_source,
    extract_entities,
    has_checkable_claims,
    toxicity,
)


@pytest.fixture(scope="module")
def bundle():
    return ControlPlane().compile_bundle()


# --------------------------------------------------------------------------
# Tier 0's free filter
# --------------------------------------------------------------------------

def test_entities_are_numbers_and_proper_nouns():
    entities = extract_entities("Priya Sharma was refunded 45230 on 12 March.")
    assert "Priya Sharma" in entities
    assert "45230" in entities


def test_sentence_openers_are_not_treated_as_entities():
    """Otherwise every sentence produces a false 'invented entity'."""
    assert extract_entities("The refund was processed.") == set()


def test_no_checkable_claims_means_skip_entirely():
    """Removes most traffic for free (IDEATION 11.5).

    Framed as "we check responses that contain checkable claims", never as
    "we check 10% randomly to save money".
    """
    assert not has_checkable_claims("Thanks for getting in touch, happy to help.")
    assert has_checkable_claims("Your balance is 45230.")


# --------------------------------------------------------------------------
# Entity-not-in-source - the highest-yield single check
# --------------------------------------------------------------------------

def test_invented_figure_is_caught():
    findings = entity_not_in_source(
        answer="Your refund of 98765 will arrive in 3 days.",
        question="When will my refund arrive?",
        sources="Refunds are processed within five working days.",
    )
    assert findings and "98765" in findings[0].evidence


def test_grounded_answer_produces_nothing():
    assert entity_not_in_source(
        answer="Your refund of 45230 is on the way.",
        question="What is my refund for account 45230?",
        sources="",
    ) == []


def test_entities_from_the_sources_are_grounded():
    assert entity_not_in_source(
        answer="Section 14 applies here.",
        question="Which section applies?",
        sources="Section 14 covers water damage.",
    ) == []


def test_invented_regulation_is_caught():
    """Demo material: the model cites something that does not exist."""
    findings = entity_not_in_source(
        answer="Under RBI Circular 2019 this is not permitted.",
        question="Is this permitted?",
        sources="Nothing in our policy documents addresses this.",
    )
    assert findings


def test_evidence_says_what_to_verify():
    """"Possible issue" is fatigue. Naming the entity is a task (12.3)."""
    findings = entity_not_in_source("The figure is 99999.", "What is it?", "")
    assert "not found in the source material" in findings[0].evidence
    assert "99999" in findings[0].evidence


def test_more_invented_entities_means_more_confidence():
    one = entity_not_in_source("Value 111.", "q", "")[0]
    many = entity_not_in_source("Values 111, 222, 333 and 444.", "q", "")[0]
    assert many.confidence > one.confidence


def test_this_is_the_check_that_reaches_d27():
    """A fabricated detail about a person is a hallucination AND a privacy
    exposure, and the known-value store cannot see it - an invented name is
    not in the customer database. It has no provenance either, so it surfaces
    here. The architecture handled the overlap; this closes the detector gap.
    """
    findings = entity_not_in_source(
        answer="I have passed this to Meena Raghavan in claims.",
        question="Who is handling my case?",
        sources="Cases are handled by the claims team.",
    )
    assert findings and "Meena Raghavan" in findings[0].evidence


# --------------------------------------------------------------------------
# Wiring into the decision engine
# --------------------------------------------------------------------------

def test_quality_findings_are_reversible(bundle):
    """The async half of IDEATION section 6 - annotate, never block."""
    finding = entity_not_in_source("The figure is 99999 exactly.", "q", "")[0]
    signal = finding.to_signal()
    assert signal.reversible

    decision = DecisionEngine().decide([signal], bundle.get("internal-knowledge"))
    assert decision.tier is Tier.ANNOTATE
    assert not decision.blocked


def test_a_quality_finding_never_blocks_even_at_full_confidence(bundle):
    """Reversible harm is annotated after release. Blocking it would pay TTFB
    for a probabilistic classifier that is wrong some of the time."""
    from controlplane.decision.tiers import Signal

    signal = Signal("hallucination", "quality", 1.0, reversible=True, evidence="x")
    assert DecisionEngine().decide([signal], bundle.get("customer-support")).tier is not Tier.BLOCK


# --------------------------------------------------------------------------
# Counterfactual probing - evidence, not a score
# --------------------------------------------------------------------------

def test_probe_produces_a_comparable_pair():
    """"Same CV, rejected under one name, advanced under another" is not
    arguable. A 0.7 bias score is."""
    def run(prompt):
        return "advance" if "Rajesh" in prompt else "reject"

    pair = CounterfactualProbe(run).probe("Assess candidate {} for the role.", "Priya", "Rajesh")
    assert pair.diverged
    assert "Priya" in pair.as_evidence() and "Rajesh" in pair.as_evidence()


def test_an_unbiased_model_shows_no_divergence():
    pair = CounterfactualProbe(lambda p: "advance").probe("Assess {}.", "A", "B")
    assert not pair.diverged


def test_probe_keeps_both_transcripts():
    """The evidence is the pair of prompts, not a summary of them."""
    pair = CounterfactualProbe(lambda p: "ok").probe("Assess {}.", "A", "B")
    assert pair.prompt_a == "Assess A." and pair.prompt_b == "Assess B."


def test_there_is_no_per_response_bias_score():
    """D12 is structural. A model recommending the male candidate 70% of the
    time produces no individually-detectable response."""
    pair = CounterfactualProbe(lambda p: "ok").probe("Assess {}.", "A", "B")
    assert not hasattr(pair, "bias_score")
    assert not hasattr(pair, "score")


# --------------------------------------------------------------------------
# Aggregate outcome distribution - the method regulators accept
# --------------------------------------------------------------------------

def test_disparity_is_counting_not_detection():
    """IDEATION 10.3: no clever detection, it is counting. It measures EFFECT
    rather than intent, which is why regulators accept it."""
    dist = OutcomeDistribution()
    for _ in range(7):
        dist.record("group_a", "advance")
    for _ in range(3):
        dist.record("group_a", "reject")
    for _ in range(3):
        dist.record("group_b", "advance")
    for _ in range(7):
        dist.record("group_b", "reject")

    assert dist.rate("group_a", "advance") == 0.7
    assert dist.disparity("advance") == pytest.approx(0.4)


def test_single_group_has_no_disparity():
    dist = OutcomeDistribution()
    dist.record("only", "advance")
    assert dist.disparity("advance") == 0.0


def test_report_states_the_method_and_its_limit():
    dist = OutcomeDistribution()
    dist.record("a", "advance")
    report = dist.report("advance")
    assert "no per-response score" in report["method"]
    assert "D12" in report["method"]


def test_pairs_feed_the_distribution():
    dist = OutcomeDistribution()
    probe = CounterfactualProbe(lambda p: "advance" if "Rajesh" in p else "reject")
    for pair in probe.sweep("Assess {}.", [("Priya", "Rajesh")] * 5):
        dist.record_pair(pair)
    assert dist.disparity("advance") == 1.0


# --------------------------------------------------------------------------
# What we did not build, labelled (D23)
# --------------------------------------------------------------------------

def test_toxicity_is_an_honest_stub():
    """Unmarked stubs are the liability on a public repo, not stubs."""
    assert toxicity("anything") == []
    assert "NOT IMPLEMENTED" in toxicity.__doc__
    assert "off-the-shelf" in toxicity.__doc__


def test_consistency_sampling_is_absent_for_a_stated_reason():
    """D11 - not omitted for lack of time.

    Sampling only detects RANDOM fabrication. Invented citations, arithmetic
    errors and reversed relations reproduce identically every sample, so
    sampling scores exactly the systematic failures as reliable. Shipping it
    would let us claim a check that is blind where it matters most.
    """
    assert consistency_sample("answer", lambda p: p) == []
    assert "NOT IMPLEMENTED" in consistency_sample.__doc__
    assert "D11" in consistency_sample.__doc__


def test_a_salutation_is_not_a_fabricated_person():
    """Found by watching the demo, not by a test.

    "Dear Priya Sharma" is a three-word capitalised run, so it was kept whole
    and compared against a question containing "Priya Sharma" - no match, and
    the greeting was reported as an entity with no provenance. The check was
    right that the exact phrase was absent and wrong about what the phrase
    was, which is the shape of false positive that teaches people to dismiss
    the flag.
    """
    question = "Customer: Priya Sharma. Balance: 45230."
    answer = "Dear Priya Sharma, your balance is 45230."

    assert entity_not_in_source(answer, question) == []
    assert "Priya Sharma" in extract_entities(answer)
    assert "Dear Priya Sharma" not in extract_entities(answer)


def test_trimming_the_greeting_does_not_hide_a_real_fabrication():
    """The guard on the fix above.

    Trimming leading stopwords must not become a way for an invented name to
    ride in behind one.
    """
    findings = entity_not_in_source(
        "Dear Priya Sharma, please contact Rahul Verma about 5427 rupees.",
        "Customer: Priya Sharma. Balance: 45230.",
    )
    assert findings
    assert "5427" in findings[0].evidence
    assert "Rahul Verma" in findings[0].evidence


def test_a_capitalised_run_does_not_span_a_line_break():
    """Also found by watching the demo.

    `\s+` between words crosses newlines, so an email's subject line and its
    salutation joined into one long "entity" that matched nothing in the
    source - and the check reported the entire greeting as fabricated. The
    noise is the damage: an evidence line nobody can act on is the alert
    fatigue the brief warns about.
    """
    answer = "Subject: Update on Your Account Balance\n\nDear Priya Sharma, hello."
    entities = extract_entities(answer)

    assert "Priya Sharma" in entities
    assert not any("\n" in e for e in entities)
    assert not any(len(e.split()) > 3 for e in entities)
