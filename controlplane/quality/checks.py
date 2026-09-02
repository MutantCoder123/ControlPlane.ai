"""Async quality checks - the reversible half of the harm split.

IDEATION section 6: hallucination, toxicity and bias are REVERSIBLE. You can
annotate them after the fact, so they run off the hot path and never cost
TTFB. Only the irreversible category has to be synchronous.

WHAT IS BUILT HERE, AND WHAT IS DELIBERATELY NOT
------------------------------------------------
Built:
  - entity-not-in-source (hallucination tier 0). IDEATION 11.5 calls it the
    highest-yield single check, and it is a pure set comparison - free. Now
    one finding PER entity, each carrying its own answer-text span (D33) so
    the exact substring can be highlighted, not just listed below the answer.
  - overclaim and unsupported-causal-claim detection (D33) - two more claim
    SHAPES from IDEATION 11.4's routing table, covering hallucination that
    carries no number or proper noun at all ("this always works", "this
    happened because of the update") and would have been invisible to the
    entity check.
  - REAL per-token confidence (D33), not a self-report and not a heavier
    formula. IDEATION 11.5 named this from the start: "token confidence
    dips - fluent sentence, low confidence exactly on a date or name...
    free if the provider exposes logprobs." Ollama does (0.33+). We read the
    actual log-probability the model assigned to the flagged span AS IT
    GENERATED IT and compare it to the response's own average - a real,
    reproducible property of the generation, never the model grading its
    own homework after the fact. See `_logprob_dip` and D33 for why
    asking the model "how confident are you" was rejected outright.
  - one counterfactual bias probe (IDEATION 10.3), producing EVIDENCE rather
    than a score.
  - toxicity (D31, Phase 8). `alt-profanity-check`'s pretrained classifier,
    off-the-shelf exactly as IDEATION 10.2 always specified - we did not
    train one, we import someone else's and report its score. First and only
    exception to Track A's stdlib-only engine; see requirements.txt.

Not built, and labelled rather than omitted (D23):
  - consistency sampling and the claim-shape routing table. D11 is the reason:
    sampling only detects RANDOM fabrication. Where the model fails
    systematically - invented citations, bad arithmetic, reversed relations -
    it fails identically every time and sampling scores it reliable. That trap
    is our strongest intellectual content precisely because we can explain it,
    and explaining it lands better than a shallow implementation of the thing
    that does not work.
  - the synchronous severe-category exception IDEATION 10.2 describes ("a
    small set of severe categories block synchronously"). Not implemented:
    the classifier is trained on whole comments, and the commit-point buffer
    releases sentence fragments, so its accuracy on a partial chunk is
    unproven - shipping a sync gate on an unvalidated signal risks blocking
    (or worse, silently passing) on the exact input it exists to catch.
    `toxicity()` therefore only ever runs in the async pass, regardless of a
    profile's `toxicity_sync` flag - see D31.

D12 - BIAS IS A PROPERTY OF A DISTRIBUTION
-------------------------------------------
There is no per-response bias score in this module and there never will be.
A model recommending the male candidate 70% of the time produces no
individually-detectable response. The probe returns a PAIR for aggregate
comparison; `OutcomeDistribution` does the counting. Anyone claiming
real-time bias detection is doing toxicity detection and mislabelling it.
"""

from __future__ import annotations

import math
import re
from collections import defaultdict
from dataclasses import dataclass, field
from typing import NamedTuple

from controlplane.decision.tiers import Signal


class TokenLogprob(NamedTuple):
    """One generated token, its real log-probability, and where it landed in
    the raw model output. Built by the orchestrator while streaming - see
    `demo/orchestrator.py`'s `_ollama_chunks` - and passed in here read-only.

    `start`/`end` are offsets into the RAW text the model generated (before
    restore() puts real values back for any placeholder), because that is
    what these numbers describe: the model's own uncertainty about the
    tokens it actually produced. Nothing here is a self-report - `logprob`
    is `ln(P(token))` as computed during generation, a real, reproducible
    (same seed, same result) number, not the model being asked afterward
    how sure it feels.
    """
    text: str
    logprob: float
    start: int
    end: int

# Numbers, dates, money, and capitalised runs - the "checkable claim" surface
# from IDEATION 11.5. No numbers, dates or proper nouns means nothing to check,
# and most traffic exits here for free.
_NUMBER_RE = re.compile(r"\b\d[\d,.]*\b")
# A run joins on SPACES, not on any whitespace. `\s+` crosses newlines, so an
# email's "...Your Account Balance\n\nDear Priya Sharma" matched as one
# eight-word entity - which appears in no source, so the whole greeting got
# reported as fabricated. A capitalised word ending one line and one starting
# the next are not a phrase.
_PROPER_RE = re.compile(r"\b[A-Z][a-z]{2,}(?:[ \t]+[A-Z][a-z]{2,})*\b")
_STOPWORDS = {
    "The", "This", "That", "These", "Those", "There", "Their", "They", "Then",
    "However", "Please", "Dear", "Thank", "Thanks", "Your", "Yours", "From",
    "Sincerely", "Regards", "Hello", "Hi", "We", "I", "It", "As", "In", "On",
    "For", "But", "And", "If", "When", "While", "You", "Our",
}


def extract_entities(text: str) -> set[str]:
    """Numbers and proper nouns - what can actually be checked.

    A single capitalised word at the start of a sentence is NOT evidence of a
    proper noun; English capitalises every sentence. Treating "Value" in
    "Value 111." as an invented entity produces a false hallucination flag,
    and false flags are the alert fatigue the brief warns about - so precision
    here is worth more than recall.

    A multi-word capitalised run ("Meena Raghavan") is kept wherever it
    appears: two capitalised words in a row is a real signal.
    """
    text = text or ""
    entities = {m.group(0) for m in _NUMBER_RE.finditer(text)}
    for match in _PROPER_RE.finditer(text):
        phrase = match.group(0)
        words = phrase.split()

        # Trim leading and trailing stopwords BEFORE judging the run. A
        # salutation glues one onto the front - "Dear Priya Sharma" is a
        # three-word capitalised run - and comparing that against a question
        # containing "Priya Sharma" finds no match, so the greeting itself
        # gets reported as a fabricated entity. The check was right that the
        # exact phrase had no provenance and wrong about what the phrase was.
        while words and words[0] in _STOPWORDS:
            words = words[1:]
        while words and words[-1] in _STOPWORDS:
            words = words[:-1]
        if not words:
            continue

        if len(words) == 1:
            if _starts_a_sentence(text, match.start()) and words[0] == match.group(0):
                continue
        entities.add(" ".join(words))
    return entities


def _starts_a_sentence(text: str, index: int) -> bool:
    # rstrip() has already removed any newline, so only punctuation matters.
    before = text[:index].rstrip()
    return not before or before[-1] in ".!?:"


@dataclass(frozen=True)
class QualityFinding:
    check: str
    detail: str
    evidence: str
    confidence: float
    # How `confidence` was computed, in the reader's own words - shown next to
    # the number in the dashboard so it is auditable rather than oracular
    # (IDEATION 12.3). Optional because early callers predate this field.
    formula: str = ""
    # Character offsets of the flagged text WITHIN THE ANSWER, so the exact
    # substring can be highlighted inline rather than only listed below it
    # (D33). None for findings that describe the whole response rather than
    # one span (toxicity, the bias probe).
    span: tuple[int, int] | None = None

    def to_signal(self, category: str = "hallucination") -> Signal:
        """Reversible by construction - this is the async half of section 6."""
        return Signal(
            category=category,
            kind="quality",
            confidence=self.confidence,
            reversible=True,
            evidence=self.evidence,
        )


#: Below this, a logprob dip is noise - token probability jitters by this much
#: on totally ordinary text (function words, punctuation) for reasons that
#: have nothing to do with truthfulness. Chosen from direct observation of
#: real generations, not a nice round number, and shown in every formula
#: string that uses it.
_LOGPROB_DIP_FLOOR = 0.0
#: A dip this large or more gets the full bonus below - deeper dips than this
#: do not carry additional information, they are just "very sure this token
#: was different from what came before."
_LOGPROB_DIP_CEILING = 2.0
#: Maximum the token-probability signal can add to the grounding-density
#: base score. Deliberately a MINORITY of the total: this is corroborating
#: evidence for a claim already flagged as ungrounded, not a standalone
#: verdict - see `_confidence_with_dip`'s docstring.
_LOGPROB_DIP_MAX_BONUS = 0.25


class _LogprobSignal(NamedTuple):
    """dip: how much less sure the model was on this span than on the
    response overall, in nats (natural-log units) - the quantity the
    confidence bonus is computed from. span_probability: the same span's own
    average probability, 0-1, converted with `exp()` purely so a human
    reads "the model was 34% sure of this figure" instead of a raw log."""
    dip: float
    span_probability: float


def _logprob_dip(
    raw_text: str | None,
    logprob_trace: list[TokenLogprob] | None,
    span_text: str,
) -> _LogprobSignal | None:
    """How much LESS sure the model was on `span_text` than on the response
    as a whole - a real, measured quantity, never a self-report.

    IDEATION 11.5 named the fingerprint directly: "fluent sentence, low
    confidence exactly on a date or name." A model reciting real, retrieved
    information is fluent throughout; a model improvising a specific detail
    tends to dip in probability exactly where the invented specific sits,
    surrounded by otherwise-confident prose. Comparing the span against the
    response's OWN average controls for the fact that some prompts are just
    harder than others for a given model - we are not claiming an absolute
    confidence threshold, only a relative dip within one generation.

    Returns None - not zero - when there is nothing to compute from: no
    trace was captured (this backend doesn't expose logprobs, or this is a
    fake model in a test), or `span_text` cannot be located verbatim in the
    raw text the model actually produced (it was restored from a
    placeholder, so the model never literally typed these characters).
    Callers must treat None as "no signal," not as "zero dip."
    """
    if not logprob_trace or not raw_text:
        return None
    idx = raw_text.find(span_text)
    if idx < 0:
        return None
    end = idx + len(span_text)
    span_tokens = [t for t in logprob_trace if t.start < end and t.end > idx]
    if not span_tokens:
        return None
    span_avg = sum(t.logprob for t in span_tokens) / len(span_tokens)
    context_avg = sum(t.logprob for t in logprob_trace) / len(logprob_trace)
    return _LogprobSignal(dip=context_avg - span_avg, span_probability=math.exp(span_avg))


def _confidence_with_dip(
    base: float, base_formula: str, signal: _LogprobSignal | None,
) -> tuple[float, str]:
    """Blend the grounding-density base score with a real per-token signal.

    The base score (how many things in this answer have no provenance) is
    unchanged from the original design and stays the majority of the number.
    The bonus is capped at `_LOGPROB_DIP_MAX_BONUS` on purpose: a
    corroborating measurement should sharpen a verdict, not let one noisy
    signal override the other. When no signal is available (no logprobs, or
    the span could not be located in the raw text), this returns `base`
    UNCHANGED - byte-identical to every caller from before this feature
    existed, which is what keeps every prior test and every non-Ollama
    backend working exactly as they did.
    """
    if signal is None:
        return base, base_formula
    scaled = max(0.0, min(signal.dip - _LOGPROB_DIP_FLOOR, _LOGPROB_DIP_CEILING))
    bonus = scaled / _LOGPROB_DIP_CEILING * _LOGPROB_DIP_MAX_BONUS
    confidence = min(0.97, base + bonus)
    formula = (
        f"{base_formula} + up to {_LOGPROB_DIP_MAX_BONUS} for a token-probability "
        f"dip ({signal.dip:+.2f} nats vs. this response's own average, the model "
        f"was {signal.span_probability:.0%} sure of this specific span as it wrote "
        f"it) - REAL per-token probability during generation, not a self-report"
    )
    return confidence, formula


def entity_not_in_source(
    answer: str,
    question: str,
    sources: str = "",
    *,
    logprob_trace: list[TokenLogprob] | None = None,
    raw_text: str | None = None,
) -> list[QualityFinding]:
    """Entities in the answer that appear in neither the question nor the sources.

    The highest-yield single check in the cascade and a pure set comparison.
    An invented figure, an invented date, or an invented person has to enter
    the answer from somewhere, and if it came from neither input it came from
    the model.

    IDEATION 11.6 - we never delete and never auto-correct. We do not know the
    right answer, only that this entity has no provenance. So the finding
    carries the entity itself, which tells the reader exactly what to verify.

    ONE FINDING PER ENTITY (D33), not one combined finding for all of them -
    each carries its own `span` into `answer`, so the dashboard can highlight
    the exact substring rather than a list below it. The grounding-density
    base score is still computed from the FULL count of ungrounded entities
    in this answer (one unexplained figure is a maybe, five is a pattern),
    shared across every finding from this call; `logprob_trace`, when given,
    additionally sharpens EACH entity's own confidence independently, since
    two ungrounded entities in the same answer can differ in how uncertain
    the model actually was generating them.

    `logprob_trace`/`raw_text` are optional and additive - omit them (every
    caller before D33, and every test) and this behaves exactly as before,
    confidence formula included, byte for byte.

    *This is also the one check that reaches D27.* A fabricated detail about a
    person is simultaneously a hallucination and a privacy exposure, and the
    known-value store cannot see it because an invented name is not in the
    customer database. It has no provenance either, so it surfaces here.
    """
    grounded = extract_entities(question) | extract_entities(sources)
    invented = sorted(e for e in extract_entities(answer) if e not in grounded)
    if not invented:
        return []

    # Scales with how much has no provenance: one unexplained figure is a
    # maybe, five is a pattern. Shared across every entity below - the
    # per-entity differentiation comes from the logprob dip, not this term.
    base = min(0.9, 0.55 + 0.1 * len(invented))
    base_formula = f"min(0.9, 0.55 + 0.1 x {len(invented)} entities_without_provenance)"

    findings = []
    for entity in invented:
        idx = answer.find(entity)
        span = (idx, idx + len(entity)) if idx >= 0 else None
        signal = _logprob_dip(raw_text, logprob_trace, entity)
        confidence, formula = _confidence_with_dip(base, base_formula, signal)
        findings.append(QualityFinding(
            check="entity_not_in_source",
            detail=f"1 of {len(invented)} entities absent from question and sources",
            # Actionable evidence, not "possible issue" - IDEATION 12.3.
            evidence=f"not found in the source material: {entity}",
            confidence=confidence,
            formula=formula,
            span=span,
        ))
    return findings


def has_checkable_claims(answer: str) -> bool:
    """Tier 0's free filter. No numbers, dates or proper nouns -> skip entirely.

    Framed as "we check responses that contain checkable claims", never as
    "we check 10% randomly to save money" (IDEATION 11.5). The first is a
    method; the second is an excuse.
    """
    return bool(extract_entities(answer))


# --------------------------------------------------------------------------
# Two more claim SHAPES (D33) - hallucination that carries no number or
# proper noun at all, and so was invisible to entity_not_in_source.
#
# IDEATION 11.4's routing table is explicit that different claim shapes fail
# differently and need different techniques; these two are the ones cheap
# enough to build as lexical detectors rather than the entailment-model
# machinery §11.2 describes for the rest of the table (not built - would
# need a real NLI model, on the same "not our production stack" footing as
# D9/D10's NER decision). Both are ANNOTATE-tier, never BLOCK, and both say
# plainly what they can and cannot tell you: a lexical marker is evidence a
# claim is WORTH A HUMAN'S ATTENTION, not proof it is false. Overclaiming a
# detector's precision is worse than a modest one, honestly labelled.
# --------------------------------------------------------------------------

#: Overclaiming language: unverifiable by text-overlap with any source,
#: because there is no number or name to look up - the claim IS the risk.
#: Loose on purpose; false positives here cost an annotation, not a block.
_ABSOLUTE_RE = re.compile(
    r"\b(always|never|guarantee[sd]?|100\s?%|completely|totally|everyone|"
    r"no ?one|impossible|certainly|definitely|without exception|"
    r"the best|the only)\b",
    re.IGNORECASE,
)

#: A causal connector, whatever immediately follows it is the claimed reason.
_CAUSAL_RE = re.compile(
    r"\b(because|due to|owing to|as a result of|caused by|resulted? in|"
    r"therefore|thus|consequently)\b",
    re.IGNORECASE,
)
#: Common connective words long enough to slip past a naive "4+ letters"
#: content-word filter but carrying no claim of their own - excluded so a
#: causal clause built entirely from function words doesn't falsely read as
#: "no overlap with source" simply because it has no content to overlap.
_CAUSAL_STOPWORDS = {
    "this", "that", "these", "those", "with", "your", "have", "will",
    "from", "they", "them", "there", "were", "been", "than", "when",
    "what", "which", "about", "would", "could", "should", "into",
}


def find_absolute_claims(
    answer: str,
    *,
    logprob_trace: list[TokenLogprob] | None = None,
    raw_text: str | None = None,
) -> list[QualityFinding]:
    """Absolute/superlative language - a claim shape, not a grounding gap.

    "This always works" cannot be checked against a source by string
    overlap - there is nothing to look up. What CAN be said is that
    unqualified, universal language is a well-known overclaiming pattern,
    worth a human's attention regardless of whether any specific fact in it
    is checkable. Confidence is a flat, modest base (this is a shape signal,
    not a count), sharpened by the same real token-probability dip
    `entity_not_in_source` uses when a trace is available - IDEATION 11.4's
    routing table calls this "filter out the uncheckable," and grading it on
    the SAME confidence scale as a grounded fact would overstate what a
    lexical marker can prove.
    """
    findings = []
    for m in _ABSOLUTE_RE.finditer(answer or ""):
        phrase = m.group(0)
        ctx_start, ctx_end = max(0, m.start() - 20), min(len(answer), m.end() + 40)
        context = answer[ctx_start:ctx_end].strip()
        base_formula = (
            "0.5 flat - absolute/superlative language, unverifiable by text "
            "overlap; flagged for a human's judgment, not scored as false"
        )
        signal = _logprob_dip(raw_text, logprob_trace, phrase)
        confidence, formula = _confidence_with_dip(0.5, base_formula, signal)
        findings.append(QualityFinding(
            check="overclaim",
            detail=f'absolute language: "{phrase}"',
            evidence=f'unverifiable absolute claim: "...{context}..."',
            confidence=confidence,
            formula=formula,
            span=(m.start(), m.end()),
        ))
    return findings


def find_unsupported_causal_claims(
    answer: str,
    question: str,
    sources: str = "",
    *,
    logprob_trace: list[TokenLogprob] | None = None,
    raw_text: str | None = None,
) -> list[QualityFinding]:
    """A stated CAUSE with no content word in common with the question or
    sources - the model asserting *why*, not just *what*, with nothing
    behind it.

    Same "not found in source" logic as `entity_not_in_source`, applied to a
    different claim shape: instead of asking "does this number/name appear
    in the source," it asks "does anything in the claimed reason appear in
    the source." A causal connector followed by a reason built entirely from
    words already present in the question or sources is left alone; one
    built from words found nowhere is exactly the "invented explanation"
    pattern - a plausible-sounding cause bolted onto a real fact.
    """
    grounding = f"{question} {sources}".lower()
    findings = []
    for m in _CAUSAL_RE.finditer(answer or ""):
        tail = answer[m.end():m.end() + 80]
        stop = re.search(r"[.!?\n]", tail)
        window_end = m.end() + (stop.start() if stop else min(len(tail), 60))
        window = answer[m.end():window_end].strip(" ,:;-")
        if not window:
            continue
        content_words = [
            w for w in re.findall(r"[A-Za-z]{4,}", window)
            if w.lower() not in _CAUSAL_STOPWORDS
        ]
        if not content_words:
            continue
        if any(w.lower() in grounding for w in content_words):
            continue  # at least one content word is grounded - leave it alone

        claim_text = answer[m.start():window_end].strip()
        base_formula = (
            "0.55 flat - causal connector followed by a reason sharing no "
            "content word with the question or sources"
        )
        signal = _logprob_dip(raw_text, logprob_trace, claim_text)
        confidence, formula = _confidence_with_dip(0.55, base_formula, signal)
        findings.append(QualityFinding(
            check="unsupported_causal_claim",
            detail="a stated cause has no supporting text in the question or sources",
            evidence=f'invented reason: "{claim_text}"',
            confidence=confidence,
            formula=formula,
            span=(m.start(), window_end),
        ))
    return findings


# --------------------------------------------------------------------------
# Counterfactual bias probing (IDEATION 10.3)
# --------------------------------------------------------------------------

#: A prompt that names the two options in its own instruction - "answer
#: with exactly one word: advance or reject" - lets us read the outcome
#: vocabulary out of the request instead of hardcoding it in Python. Loose on
#: purpose (any phrase before the colon, "word" or "term" or nothing) because
#: the two option words after "or" are the only part that has to be exact.
_FORCED_CHOICE_RE = re.compile(
    r"exactly one (?:word|term)[^:]*:\s*([A-Za-z][\w-]*)\s+or\s+([A-Za-z][\w-]*)",
    re.IGNORECASE,
)


def find_subject(text: str) -> str | None:
    """The counterfactual slot in an ARBITRARY request - no `{}` authored in
    advance. Reuses `_PROPER_RE`/`_STOPWORDS`, the exact detector
    `entity_not_in_source` uses for hallucination, rather than inventing a
    second one: "does this request name a person" is the same question
    whether we're asking "is this grounded" or "is this swappable."

    Deliberately requires TWO OR MORE capitalised words. A single
    capitalised word is too likely to be a company, a place, or a sentence
    opener (the same ambiguity `extract_entities` already guards against) -
    and a false subject swapped into the wrong span would silently produce
    two prompts that are not actually a controlled comparison, which is
    worse than correctly saying "nothing to vary here."

    Returns the first candidate in reading order - one subject, matching how
    every existing probe scenario (a candidate, a claimant, a customer) has
    exactly one person the request is about. Returns None when there isn't
    one, which is a fact about the request, not a failure of the detector.
    """
    for match in _PROPER_RE.finditer(text or ""):
        words = match.group(0).split()
        while words and words[0] in _STOPWORDS:
            words = words[1:]
        while words and words[-1] in _STOPWORDS:
            words = words[:-1]
        if len(words) >= 2:
            return " ".join(words)
    return None


def parse_forced_choice(prompt: str) -> tuple[str, str] | None:
    """The two outcome words, read out of the PROMPT's own instruction.

    Replaces a hardcoded vocabulary ("advance"/"reject" baked into Python)
    with whatever a given prompt actually asks for - "approve or deny",
    "yes or no", "advance or reject" all work, and a template author never
    has to touch this module to add a new one. Only fires for prompts that
    genuinely ask for a forced choice; free-form prompts correctly get
    nothing back, which routes them to the tier-0 evidence path instead of a
    fabricated label.
    """
    m = _FORCED_CHOICE_RE.search(prompt or "")
    if not m:
        return None
    return (m.group(1).lower(), m.group(2).lower())


def classify_forced_choice(reply: str, options: tuple[str, str]) -> str:
    """Which of the two named options a reply picked, or "unclear".

    Substring match, not exact-match, because a model rarely replies with
    ONLY the bare word - "I'd advance this candidate." still contains
    "advance". Both options present, or neither, is reported as "unclear"
    rather than guessed at: a forced-choice prompt that didn't get a clean
    forced-choice answer is itself worth knowing, not worth papering over.
    """
    low = (reply or "").lower()
    a, b = options
    has_a, has_b = a in low, b in low
    if has_a and not has_b:
        return a
    if has_b and not has_a:
        return b
    return "unclear"


@dataclass(frozen=True)
class CounterfactualPair:
    """Two runs of the same request, one attribute changed.

    Evidence, not a score. "Classifier rated this 0.7 biased" is arguable;
    "same CV, rejected under one name, advanced under another, here are both
    transcripts" is not.
    """

    attribute: str
    variant_a: str
    variant_b: str
    outcome_a: str
    outcome_b: str
    prompt_a: str = ""
    prompt_b: str = ""

    @property
    def diverged(self) -> bool:
        return self.outcome_a != self.outcome_b

    def as_evidence(self) -> str:
        return (
            f"same request, {self.attribute} changed "
            f"({self.variant_a} -> {self.variant_b}): "
            f"{self.outcome_a} -> {self.outcome_b}"
        )


class NoSubjectToVary(ValueError):
    """Raised by `build_variants()` (and therefore `probe()`) when a prompt
    has neither a `{}` slot nor a detectable subject - there is no
    counterfactual axis in this request, which is a fact about the request,
    not something to guess around."""


def build_variants(prompt: str, variant_a: str, variant_b: str) -> tuple[str, str]:
    """The two counterfactual prompts, found two ways, in this order:

      1. An explicit `{}`, authored on purpose - still supported, and still
         the right choice when a template is reused often enough to be worth
         writing once.
      2. `find_subject()` - no authoring at all. Any prompt that already
         names a person ("Draft a decision for Rajesh Kumar's claim")
         becomes probeable automatically, which is the point: bias probing
         should not require a human to pre-write a `{}` template for every
         shape of request that comes through.

    Raises `NoSubjectToVary` when neither applies, rather than silently
    returning a pair built from an unmodified prompt - a pair that cannot
    possibly diverge is not evidence of anything. Shared by `probe()` below
    and by `demo/server.py`'s `/demo/bias` route, so there is exactly one
    place this decision is made, not two that could drift apart.
    """
    if "{}" in prompt:
        return prompt.replace("{}", variant_a), prompt.replace("{}", variant_b)

    subject = find_subject(prompt)
    if subject is None:
        raise NoSubjectToVary(
            "no `{}` slot and no detectable subject (two or more "
            "capitalised words) - nothing in this prompt to vary"
        )
    # All occurrences, not just the first: a subject mentioned twice in one
    # prompt must read as the same person in both variants, not a name
    # mismatched partway through.
    return prompt.replace(subject, variant_a), prompt.replace(subject, variant_b)


class CounterfactualProbe:
    """Vary the attribute instead of hiding it.

    IDEATION 10.4 rejects masking demographic terms as *fairness through
    unawareness* - the model reconstructs the attribute from postcode, school
    and phrasing, so masking removes our ability to DETECT bias without
    removing the bias. Worse than nothing, because we then believe we are safe.

    What we keep is the same primitive, inverted. Masking is a bad mitigation
    and an excellent measurement instrument, and there is no unmasking problem
    because we compare rather than restore.

    Runs as a scheduled job on sampled traffic, never per request.
    """

    def __init__(self, run, *, attribute: str = "name") -> None:
        self.run = run
        self.attribute = attribute

    def probe(self, prompt: str, variant_a: str, variant_b: str) -> CounterfactualPair:
        """Build both variants of `prompt` via `build_variants()`, then run
        each. Raises `NoSubjectToVary` when the prompt has nothing to vary -
        see `build_variants()`.
        """
        prompt_a, prompt_b = build_variants(prompt, variant_a, variant_b)

        return CounterfactualPair(
            attribute=self.attribute,
            variant_a=variant_a,
            variant_b=variant_b,
            outcome_a=self.run(prompt_a),
            outcome_b=self.run(prompt_b),
            prompt_a=prompt_a,
            prompt_b=prompt_b,
        )

    def sweep(self, prompt: str, pairs) -> list[CounterfactualPair]:
        return [self.probe(prompt, a, b) for a, b in pairs]


class OutcomeDistribution:
    """Counting, not clever detection.

    IDEATION 10.3: record outcomes alongside the attribute and compare rates
    over hundreds of requests. This is the method regulators accept, because
    it measures EFFECT rather than intent.
    """

    def __init__(self) -> None:
        self._counts: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))

    def record(self, group: str, outcome: str) -> None:
        self._counts[group][outcome] += 1

    def record_pair(self, pair: CounterfactualPair) -> None:
        self.record(pair.variant_a, pair.outcome_a)
        self.record(pair.variant_b, pair.outcome_b)

    def rate(self, group: str, outcome: str) -> float:
        total = sum(self._counts[group].values())
        return self._counts[group][outcome] / total if total else 0.0

    def disparity(self, outcome: str) -> float:
        """Widest gap in `outcome` rate between any two groups."""
        rates = [self.rate(g, outcome) for g in self._counts]
        return max(rates) - min(rates) if len(rates) > 1 else 0.0

    def report(self, outcome: str) -> dict:
        return {
            "outcome": outcome,
            "groups": {
                g: {"rate": round(self.rate(g, outcome), 4), "n": sum(c.values())}
                for g, c in sorted(self._counts.items())
            },
            "disparity": round(self.disparity(outcome), 4),
            "method": (
                "aggregate outcome-distribution monitoring. Bias is a property "
                "of a distribution, so there is no per-response score here - "
                "by nature, not by choice (D12)."
            ),
        }


# --------------------------------------------------------------------------
# Toxicity (D31) - off-the-shelf, exactly as IDEATION 10.2 always specified
# --------------------------------------------------------------------------

#: Below this, `predict_prob`'s score is noise on ordinary business text -
#: hedges, negation and quoted profanity ("the ticket says the customer
#: called us idiots") sit in the 0.1-0.4 range. Flagging there would be the
#: alert-fatigue failure D26 exists to prevent.
TOXICITY_THRESHOLD = 0.5


def toxicity(answer: str) -> list[QualityFinding]:
    """Off-the-shelf classifier, on the async path - IDEATION 10.2, built.

    `alt-profanity-check` ships a pretrained linear SVM over character
    n-grams: its own `model.joblib` and `vectorizer.joblib`, bundled inside
    the package. We import someone else's classifier and report its score;
    training one ourselves stays on the do-not-build list (D31) for the same
    reason a hand-rolled bias classifier does - we are not positioned to
    validate our own accuracy or audit our own bias, and a vendor's model
    that turns out to be wrong is their liability, not an argument against
    the architecture.

    Fails open, like the reversible half generally does (DRAWBACK.md notes
    reversible checks fail open and get marked `unverified` rather than
    stopping the response): if the dependency is missing or the call raises,
    this returns no finding rather than crash a request over a check whose
    entire job is to catch something that can still be corrected afterwards.

    NOT covered here: the "small set of severe categories block
    synchronously" exception IDEATION 10.2 also describes. See the module
    docstring and D31 for why that stays unbuilt - the classifier is trained
    on whole comments, and the commit-point buffer releases fragments.
    """
    text = (answer or "").strip()
    if not text:
        return []

    try:
        from profanity_check import predict_prob
        score = float(predict_prob([text])[0])
    except Exception:
        # Missing dependency, a corrupted install, anything - fail open.
        return []

    if score < TOXICITY_THRESHOLD:
        return []

    return [
        QualityFinding(
            check="toxicity",
            detail="response scored above the toxicity threshold",
            evidence=(
                f"toxicity classifier score {score:.2f} "
                f"(threshold {TOXICITY_THRESHOLD}) - alt-profanity-check, "
                "a pretrained linear SVM, not a model we trained"
            ),
            confidence=round(score, 3),
            formula=f"alt-profanity-check.predict_prob() >= {TOXICITY_THRESHOLD}",
        )
    ]


def consistency_sample(answer: str, resample) -> list[QualityFinding]:
    """NOT IMPLEMENTED in the prototype, and not merely for lack of time.

    D11: sampling detects RANDOM fabrication. Invented citations, arithmetic
    errors and reversed relations reproduce identically every sample, so
    sampling scores exactly the systematic failures as reliable. Shipping it
    would let us claim a check that is blind where it matters most.

    The claim-shape routing table (IDEATION 11.4) is how you fix that, and it
    is our strongest intellectual content as an explanation.
    """
    return []
