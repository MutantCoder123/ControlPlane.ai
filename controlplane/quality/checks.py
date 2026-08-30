"""Async quality checks - the reversible half of the harm split.

IDEATION section 6: hallucination, toxicity and bias are REVERSIBLE. You can
annotate them after the fact, so they run off the hot path and never cost
TTFB. Only the irreversible category has to be synchronous.

WHAT IS BUILT HERE, AND WHAT IS DELIBERATELY NOT
------------------------------------------------
Built:
  - entity-not-in-source (hallucination tier 0). IDEATION 11.5 calls it the
    highest-yield single check, and it is a pure set comparison - free.
  - one counterfactual bias probe (IDEATION 10.3), producing EVIDENCE rather
    than a score.

Not built, and labelled rather than omitted (D23):
  - consistency sampling and the claim-shape routing table. D11 is the reason:
    sampling only detects RANDOM fabrication. Where the model fails
    systematically - invented citations, bad arithmetic, reversed relations -
    it fails identically every time and sampling scores it reliable. That trap
    is our strongest intellectual content precisely because we can explain it,
    and explaining it lands better than a shallow implementation of the thing
    that does not work.
  - a toxicity classifier. Off-the-shelf in production; a labelled stub here.

D12 - BIAS IS A PROPERTY OF A DISTRIBUTION
-------------------------------------------
There is no per-response bias score in this module and there never will be.
A model recommending the male candidate 70% of the time produces no
individually-detectable response. The probe returns a PAIR for aggregate
comparison; `OutcomeDistribution` does the counting. Anyone claiming
real-time bias detection is doing toxicity detection and mislabelling it.
"""

from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass, field

from controlplane.decision.tiers import Signal

# Numbers, dates, money, and capitalised runs - the "checkable claim" surface
# from IDEATION 11.5. No numbers, dates or proper nouns means nothing to check,
# and most traffic exits here for free.
_NUMBER_RE = re.compile(r"\b\d[\d,.]*\b")
_PROPER_RE = re.compile(r"\b[A-Z][a-z]{2,}(?:\s+[A-Z][a-z]{2,})*\b")
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
        if len(words) == 1:
            if words[0] in _STOPWORDS:
                continue
            if _starts_a_sentence(text, match.start()):
                continue
        entities.add(phrase)
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

    def to_signal(self, category: str = "hallucination") -> Signal:
        """Reversible by construction - this is the async half of section 6."""
        return Signal(
            category=category,
            kind="quality",
            confidence=self.confidence,
            reversible=True,
            evidence=self.evidence,
        )


def entity_not_in_source(
    answer: str, question: str, sources: str = ""
) -> list[QualityFinding]:
    """Entities in the answer that appear in neither the question nor the sources.

    The highest-yield single check in the cascade and a pure set comparison.
    An invented figure, an invented date, or an invented person has to enter
    the answer from somewhere, and if it came from neither input it came from
    the model.

    IDEATION 11.6 - we never delete and never auto-correct. We do not know the
    right answer, only that this entity has no provenance. So the finding
    carries the entity itself, which tells the reader exactly what to verify.

    *This is also the one check that reaches D27.* A fabricated detail about a
    person is simultaneously a hallucination and a privacy exposure, and the
    known-value store cannot see it because an invented name is not in the
    customer database. It has no provenance either, so it surfaces here.
    """
    grounded = extract_entities(question) | extract_entities(sources)
    invented = sorted(e for e in extract_entities(answer) if e not in grounded)
    if not invented:
        return []

    shown = ", ".join(invented[:5])
    more = f" (+{len(invented) - 5} more)" if len(invented) > 5 else ""
    return [
        QualityFinding(
            check="entity_not_in_source",
            detail=f"{len(invented)} entities absent from question and sources",
            # Actionable evidence, not "possible issue" - IDEATION 12.3.
            evidence=f"not found in the source material: {shown}{more}",
            # Scales with how much has no provenance: one unexplained figure
            # is a maybe, five is a pattern.
            confidence=min(0.9, 0.55 + 0.1 * len(invented)),
        )
    ]


def has_checkable_claims(answer: str) -> bool:
    """Tier 0's free filter. No numbers, dates or proper nouns -> skip entirely.

    Framed as "we check responses that contain checkable claims", never as
    "we check 10% randomly to save money" (IDEATION 11.5). The first is a
    method; the second is an excuse.
    """
    return bool(extract_entities(answer))


# --------------------------------------------------------------------------
# Counterfactual bias probing (IDEATION 10.3)
# --------------------------------------------------------------------------


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
        prompt_a = prompt.replace("{}", variant_a)
        prompt_b = prompt.replace("{}", variant_b)
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
# Not implemented - labelled, per D23
# --------------------------------------------------------------------------


def toxicity(answer: str) -> list[QualityFinding]:
    """NOT IMPLEMENTED in the prototype.

    Production uses an off-the-shelf classifier on the async path, with a
    small set of severe categories blocking synchronously (IDEATION 10.2).
    Training our own is explicitly on the do-not-build list.

    Labelled rather than stubbed silently: on a public repo an unmarked gap
    reads as vapour, while a named one reads as scope control (D23).
    """
    return []


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
