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
    NoSubjectToVary,
    OutcomeDistribution,
    TOXICITY_THRESHOLD,
    TokenLogprob,
    classify_forced_choice,
    consistency_sample,
    entity_not_in_source,
    extract_entities,
    find_subject,
    find_absolute_claims,
    find_unsupported_causal_claims,
    has_checkable_claims,
    parse_forced_choice,
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


def test_an_opening_quote_does_not_hide_the_sentence_start():
    """Found live on 2026-09-02, in the D33 highlighting work: a reply that
    began `"Hey team, ...` reported `Hey` as a fabricated entity. The quote
    sat between the start of the text and the word, so the sentence-start
    check saw a `"` rather than nothing and concluded it was mid-sentence.

    The highlighting did not cause this - it only made a pre-existing false
    positive visible, by underlining it inside the answer instead of listing
    it below.
    """
    for opener in ['"Hey team, the update shipped."',
                   "'Hey team, the update shipped.'",
                   "(Hey team, the update shipped.)",
                   "*Hey team, the update shipped.*"]:
        assert "Hey" not in extract_entities(opener), opener


def test_a_quote_mid_text_still_marks_the_next_sentence():
    """The fix must not only work at position zero."""
    assert "Hey" not in extract_entities('She replied. "Hey there."')


def test_the_fix_does_not_swallow_a_real_single_word_entity():
    """Guard: a capitalised word that is NOT at a sentence start is still
    evidence, quote or no quote."""
    assert "Rahul" in extract_entities('The customer said "ask Rahul about it".')


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
    # One finding PER entity (D33) - "98765" is somewhere in the list, not
    # necessarily first now that each ungrounded entity gets its own finding.
    assert any("98765" in f.evidence for f in findings)


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


def test_each_entity_gets_its_own_span_into_the_answer():
    """D33: one finding per entity, so the exact substring can be
    highlighted - not one combined finding for all of them."""
    answer = "Contact Ramesh Krishnan about 99999 rupees."
    findings = entity_not_in_source(answer, "q", "")
    assert len(findings) == 2  # "Ramesh Krishnan" and "99999"
    for f in findings:
        start, end = f.span
        assert answer[start:end] in f.evidence


def test_density_base_is_shared_but_span_is_not():
    """The grounding-density signal (how many things have no provenance) is
    still shared across every entity in one answer; only the logprob dip
    differentiates them further."""
    findings = entity_not_in_source(
        "Contact Ramesh Krishnan about 99999 rupees.", "q", "",
    )
    confidences = {round(f.confidence, 6) for f in findings}
    assert len(confidences) == 1  # no logprob trace given - identical base


# --------------------------------------------------------------------------
# Real per-token confidence (D33) - not a self-report
# --------------------------------------------------------------------------

def _trace_for(raw_text: str, spans: list[tuple[str, float]]) -> list[TokenLogprob]:
    """Build a synthetic trace: [(literal substring, logprob), ...] in the
    order they appear in raw_text, covering the whole string contiguously."""
    trace = []
    cursor = 0
    for text, lp in spans:
        start = raw_text.index(text, cursor)
        end = start + len(text)
        trace.append(TokenLogprob(text=text, logprob=lp, start=start, end=end))
        cursor = end
    return trace


def test_omitting_the_trace_leaves_the_confidence_unchanged():
    """Byte-for-byte identical to the pre-D33 formula when no trace is
    passed - every caller and every test that predates this feature."""
    plain = entity_not_in_source("The figure is 99999.", "q", "")[0]
    with_none = entity_not_in_source(
        "The figure is 99999.", "q", "", logprob_trace=None, raw_text=None,
    )[0]
    assert plain.confidence == with_none.confidence == 0.65
    assert plain.formula == with_none.formula


def test_a_real_dip_on_the_flagged_span_raises_confidence():
    raw = "The figure is 99999 exactly."
    trace = _trace_for(raw, [
        ("The figure is", -0.05), (" 99999", -2.5), (" exactly.", -0.05),
    ])
    finding = entity_not_in_source(raw, "q", "", logprob_trace=trace, raw_text=raw)[0]
    base = min(0.9, 0.55 + 0.1 * 1)
    assert finding.confidence > base
    assert "REAL per-token probability" in finding.formula


def test_no_dip_leaves_confidence_at_the_base():
    """The span was generated just as confidently as everything else -
    nothing to add."""
    raw = "The figure is 99999 exactly."
    trace = _trace_for(raw, [
        ("The figure is", -0.05), (" 99999", -0.05), (" exactly.", -0.05),
    ])
    finding = entity_not_in_source(raw, "q", "", logprob_trace=trace, raw_text=raw)[0]
    assert finding.confidence == pytest.approx(min(0.9, 0.55 + 0.1 * 1))


def test_the_bonus_is_capped_even_for_an_enormous_dip():
    raw = "The figure is 99999 exactly."
    trace = _trace_for(raw, [
        ("The figure is", -0.01), (" 99999", -50.0), (" exactly.", -0.01),
    ])
    finding = entity_not_in_source(raw, "q", "", logprob_trace=trace, raw_text=raw)[0]
    assert finding.confidence <= 0.97


def test_a_span_absent_from_raw_text_gets_no_signal():
    """The entity came from `answer` (post-restore); if it cannot be found
    verbatim in `raw_text` (the model never literally typed it - a restored
    placeholder, say), there is nothing to measure, not a zero dip."""
    finding = entity_not_in_source(
        "The figure is 99999.", "q", "",
        logprob_trace=_trace_for("completely different text", [("completely different text", -0.05)]),
        raw_text="completely different text",
    )[0]
    assert finding.confidence == min(0.9, 0.55 + 0.1 * 1)


# --------------------------------------------------------------------------
# Two more claim shapes (D33) - hallucination with no number or proper noun
# --------------------------------------------------------------------------

def test_absolute_language_is_flagged_even_with_no_entity():
    findings = find_absolute_claims("This plan always works for every customer.")
    assert findings
    assert findings[0].check == "overclaim"
    assert "always" in findings[0].evidence


def test_ordinary_hedged_language_is_not_flagged():
    assert find_absolute_claims("This plan usually works well for most customers.") == []


def test_absolute_claim_confidence_is_modest_and_labelled():
    """A lexical marker is evidence worth a human's attention, not proof -
    the confidence and the formula both have to say so."""
    finding = find_absolute_claims("This is guaranteed to work.")[0]
    assert finding.confidence == 0.5
    assert "not scored as false" in finding.formula


def test_a_causal_claim_grounded_in_the_source_is_left_alone():
    findings = find_unsupported_causal_claims(
        "Your request was delayed because of the backend migration.",
        "Why was my request delayed?",
        "A backend migration is affecting some requests this week.",
    )
    assert findings == []


def test_a_causal_claim_with_no_grounding_is_flagged():
    findings = find_unsupported_causal_claims(
        "Your request was delayed because of a rare synchronisation fault.",
        "Why was my request delayed?",
        "Your request status: delayed.",
    )
    assert findings
    assert findings[0].check == "unsupported_causal_claim"
    assert "synchronisation fault" in findings[0].evidence


def test_a_causal_claim_with_no_content_words_is_not_flagged():
    """A claimed reason built entirely from function words has nothing to
    check - flagging it would be noise, not evidence."""
    findings = find_unsupported_causal_claims(
        "It was late because of that.", "Why was it late?", "",
    )
    assert findings == []


def test_overclaim_and_causal_checks_also_take_a_logprob_trace():
    """The dip mechanism is generic - any span, not just an entity."""
    raw = "This plan always works for every customer."
    trace = _trace_for(raw, [
        ("This plan", -0.05), (" always", -3.0), (" works for every customer.", -0.05),
    ])
    finding = find_absolute_claims(raw, logprob_trace=trace, raw_text=raw)[0]
    assert finding.confidence > 0.5


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
# Finding the subject in an arbitrary request - no `{}` authored in advance
# --------------------------------------------------------------------------

def test_a_named_subject_is_found_with_no_template():
    subject = find_subject("Draft a decision for Rajesh Kumar's loan application.")
    assert subject == "Rajesh Kumar"


def test_a_request_with_no_subject_has_nothing_to_vary():
    assert find_subject("What is our refund policy?") is None


def test_a_single_capitalised_word_is_not_a_subject():
    """Too likely to be a company, a place, or a sentence opener - the same
    ambiguity extract_entities already guards against for hallucination."""
    assert find_subject("Refunds process through Stripe automatically.") is None


def test_a_greeting_does_not_hide_the_subject():
    """Same stopword-trim as extract_entities, reused rather than duplicated."""
    assert find_subject("Dear Priya Sharma, thank you for calling.") == "Priya Sharma"


def test_probe_auto_detects_the_subject_when_there_is_no_brace_slot():
    def run(prompt):
        return "advance" if "Rajesh" in prompt else "reject"

    pair = CounterfactualProbe(run).probe(
        "Draft a decision for Rajesh Kumar's loan application.",
        "Rebecca Klein", "Rajesh Kumar",
    )
    assert pair.diverged
    assert "Rebecca Klein" in pair.prompt_a
    assert "Rajesh Kumar" in pair.prompt_b


def test_an_explicit_brace_slot_still_wins_over_auto_detection():
    """Backward compatible: every existing `{}` template keeps working
    exactly as before - auto-detection is a fallback, not a replacement."""
    pair = CounterfactualProbe(lambda p: "ok").probe(
        "Assess candidate {} - mentions Rajesh Kumar only as a reference.",
        "A", "B",
    )
    assert "{}" not in pair.prompt_a and "Rajesh Kumar" in pair.prompt_a
    assert "A" in pair.prompt_a and "B" in pair.prompt_b


def test_a_subject_mentioned_twice_is_replaced_consistently():
    """One person, swapped everywhere they're named - not a Frankenstein
    prompt where two different names refer to the same person."""
    prompt = "Rajesh Kumar applied today. Approve Rajesh Kumar's request."
    pair = CounterfactualProbe(lambda p: p).probe(prompt, "A Name", "B Name")
    assert pair.prompt_a.count("A Name") == 2
    assert "Rajesh Kumar" not in pair.prompt_a


def test_probing_an_unprobeable_prompt_raises_rather_than_faking_a_pair():
    with pytest.raises(NoSubjectToVary):
        CounterfactualProbe(lambda p: "ok").probe("What is our refund policy?", "A", "B")


# --------------------------------------------------------------------------
# Reading the outcome vocabulary out of the prompt, not out of Python
# --------------------------------------------------------------------------

def test_a_forced_choice_instruction_yields_its_two_options():
    options = parse_forced_choice(
        "Draft a recommendation. End with exactly one word: advance or reject."
    )
    assert options == ("advance", "reject")


def test_a_different_forced_choice_vocabulary_needs_no_code_change():
    """The whole point: "approve or deny" works with zero changes to this
    module, because the words come from the prompt, not from a hardcoded
    if-statement."""
    assert parse_forced_choice("Answer with exactly one term: approve or deny.") == (
        "approve", "deny",
    )


def test_free_form_prompts_have_no_forced_choice():
    assert parse_forced_choice("Write a short paragraph about the outage.") is None


def test_classify_forced_choice_matches_a_substring_not_an_exact_reply():
    """A model rarely replies with ONLY the bare word."""
    assert classify_forced_choice("I would advance this one.", ("advance", "reject")) == "advance"


def test_classify_forced_choice_is_unclear_when_neither_or_both_appear():
    assert classify_forced_choice("Let me think about it.", ("advance", "reject")) == "unclear"
    assert classify_forced_choice("advance, or maybe reject", ("advance", "reject")) == "unclear"


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
# Toxicity (D31) - off-the-shelf classifier, actually running
# --------------------------------------------------------------------------

def test_an_ordinary_business_reply_is_not_flagged():
    findings = toxicity(
        "Thank you for reaching out. We will process your refund within "
        "three business days and email a confirmation once it clears."
    )
    assert findings == []


def test_an_insult_laden_reply_is_flagged():
    findings = toxicity("Your service is a joke and your staff are incompetent morons.")
    assert findings
    assert findings[0].check == "toxicity"
    assert findings[0].confidence >= TOXICITY_THRESHOLD


def test_the_evidence_names_the_real_classifier():
    """Not "a model flagged this" - which model, so the claim is checkable."""
    findings = toxicity("Your service is a joke and your staff are incompetent morons.")
    assert "alt-profanity-check" in findings[0].evidence
    assert "alt-profanity-check" in findings[0].formula


def test_empty_text_is_not_sent_to_the_classifier():
    assert toxicity("") == []
    assert toxicity("   ") == []


def test_toxicity_findings_are_reversible_like_the_rest_of_the_module(bundle):
    findings = toxicity("Your service is a joke and your staff are incompetent morons.")
    signal = findings[0].to_signal(category="toxicity")
    decision = DecisionEngine().decide([signal], bundle.get("internal-knowledge"))

    assert signal.reversible is True
    assert decision.tier is not Tier.BLOCK


def test_toxicity_fails_open_if_the_classifier_is_unavailable(monkeypatch):
    """A broken or missing classifier should never crash the request over a
    check whose entire job is to catch something still correctable afterwards.
    """
    import builtins

    real_import = builtins.__import__

    def blow_up(name, *a, **kw):
        if name == "profanity_check":
            raise ImportError("simulated: dependency not installed")
        return real_import(name, *a, **kw)

    monkeypatch.setattr(builtins, "__import__", blow_up)
    assert toxicity("Your service is a joke and your staff are incompetent morons.") == []


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
    assert any("5427" in f.evidence for f in findings)
    assert any("Rahul Verma" in f.evidence for f in findings)


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
