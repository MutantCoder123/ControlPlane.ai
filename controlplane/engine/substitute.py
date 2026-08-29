"""SubstitutionEngine - TRACK A owns this. Assembly of the two tiers.

Implements the API in CONTRACTS.md section 3.

The claim this makes possible (IDEATION section 9.3): the provider never
receives real personal data AT ALL. That is a materially stronger compliance
statement than "we redact when we detect", and it is why we substitute rather
than destroy - the answer stays complete, so there is no utility-versus-safety
trade to argue about.

Two rules carry design decisions:

1. SAME ENTITY -> SAME PLACEHOLDER, within one request. If "Priya Sharma"
   appears three times it is [[CUST_A]] all three times, or the model can no
   longer tell it is one person and the answer degrades.

2. NEVER SUBSTITUTE OPERANDS (D16). Sensitivity lives in the linkage, not the
   value: "45230" alone is meaningless, "Priya's balance is 45230" is
   sensitive because of the name. Swap the name, let the number through, and
   the model's arithmetic is still correct.
   *** Break the linkage, preserve the arithmetic. ***

The `role` comes from the seed data and is never inferred at runtime - if the
engine has to guess which numbers are safe to compute with, it will guess
wrong. The genuine failure case, where the identifier IS the operand
("validate this account number's checksum"), is not solvable here: we emit
the finding and P6 routes it to a human.
"""

from __future__ import annotations

from dataclasses import dataclass

from controlplane.engine.api import (
    EngineConfig,
    Finding,
    RestoreResult,
    ScanResult,
)
from controlplane.engine.knownvalue import KnownValueStore, normalise
from controlplane.engine import patterns
from controlplane.engine.placeholders import find_placeholders, make_placeholder, tolerant_pattern


@dataclass(frozen=True)
class _Candidate:
    """One tier's opinion about one span, before the tiers are reconciled."""

    span: tuple[int, int]
    text: str
    category: str
    action: str
    confidence: float
    record_ref: str | None
    role: str
    kind: str


class SubstitutionEngine:
    """Scan text, swap identifiers for placeholders, put them back after."""

    def __init__(self, records_path: str, config: EngineConfig | None = None) -> None:
        self.config = config or EngineConfig()
        self.store = KnownValueStore.from_jsonl(
            records_path,
            capacity=self.config.bloom_capacity,
            error_rate=self.config.bloom_error_rate,
        )

    # -- inbound -----------------------------------------------------------

    def scan_inbound(self, text: str) -> ScanResult:
        """Make `text` safe to send upstream.

        Never raises. A malformed prompt comes back as blocked, because the
        gateway sits on the request path and must be able to trust that
        (CONTRACTS.md section 3). Failing closed here is also the documented
        policy for the credential/PII checker (IDEATION section 17): a broken
        app beats a leak.
        """
        try:
            return self._scan_inbound(text)
        except Exception as exc:  # pragma: no cover - defensive by design
            return ScanResult(
                text="",
                blocked=True,
                block_reason=f"scanner error, failing closed: {type(exc).__name__}: {exc}",
            )

    def _scan_inbound(self, text: str) -> ScanResult:
        if not isinstance(text, str):
            return ScanResult(text="", blocked=True, block_reason="prompt is not text")
        if not text:
            return ScanResult(text="")

        candidates = self._reconcile(self._candidates(text))

        findings: list[Finding] = []
        mapping: dict[str, str] = {}
        assigned: dict[tuple[str, str], str] = {}
        counters: dict[str, int] = {}
        blocked_reasons: list[str] = []
        out = text

        # Right to left, so replacing never invalidates a span we have not
        # used yet.
        for cand in sorted(candidates, key=lambda c: c.span[0], reverse=True):
            if cand.role == "operand":
                # D16, made visible. We looked this value up, we know exactly
                # what it is, and we are deliberately leaving it alone so the
                # arithmetic downstream still works.
                continue

            start, end = cand.span

            if cand.action == "block":
                # Not placeholdered: we are not sending it, so there is
                # nothing to restore. A non-placeholder marker keeps it out of
                # the unrestored alarm too.
                out = out[:start] + f"<redacted:{cand.category}>" + out[end:]
                blocked_reasons.append(cand.category)
                findings.append(
                    Finding(
                        kind=cand.kind,
                        category=cand.category,
                        action="block",
                        span=cand.span,
                        confidence=cand.confidence,
                        record_ref=cand.record_ref,
                        placeholder=None,
                    )
                )
                continue

            key = (cand.category, normalise(cand.text))
            placeholder = assigned.get(key)
            if placeholder is None:
                index = counters.get(cand.category, 0)
                counters[cand.category] = index + 1
                placeholder = make_placeholder(cand.category, index)
                assigned[key] = placeholder
                mapping[placeholder] = cand.text

            out = out[:start] + placeholder + out[end:]
            findings.append(
                Finding(
                    kind=cand.kind,
                    category=cand.category,
                    action="substitute",
                    span=cand.span,
                    confidence=cand.confidence,
                    record_ref=cand.record_ref,
                    placeholder=placeholder,
                )
            )

        findings.sort(key=lambda f: f.span[0])

        # Replacement runs right to left so spans stay valid, which leaves the
        # mapping in reverse text order. Re-emit it left to right: a consumer
        # reasonably expects `next(iter(mapping))` to be the first entity in
        # the prompt, and quietly getting the last one is the kind of surprise
        # that produces a wrong-looking demo.
        ordered = {
            f.placeholder: mapping[f.placeholder]
            for f in findings
            if f.placeholder and f.placeholder in mapping
        }

        blocked = bool(blocked_reasons)
        return ScanResult(
            text=out,
            findings=findings,
            mapping=ordered,
            blocked=blocked,
            block_reason=(
                "credential in prompt: " + ", ".join(sorted(set(blocked_reasons)))
                if blocked
                else None
            ),
        )

    # -- outbound ----------------------------------------------------------

    def scan_outbound(self, text: str) -> ScanResult:
        """Check a model response before it reaches the reader.

        The asymmetry (IDEATION section 9.6): inbound we substitute, outbound
        we block. Outbound volume is lower, so it can afford more scrutiny,
        and the harm is different - here the risk is the reader seeing
        something they are not cleared for, or the model emitting a live
        credential, which is irreversible the moment it renders.

        Run this BEFORE restore(): at that point no real value should be
        present, so a known-value hit means something leaked that we never
        sent, which is worth knowing about loudly.
        """
        try:
            if not isinstance(text, str) or not text:
                return ScanResult(text=text if isinstance(text, str) else "")

            candidates = self._reconcile(self._candidates(text))
            findings: list[Finding] = []
            reasons: list[str] = []
            out = text

            for cand in sorted(candidates, key=lambda c: c.span[0], reverse=True):
                if cand.role == "operand":
                    continue
                if cand.action != "block":
                    findings.append(
                        Finding(
                            kind=cand.kind,
                            category=cand.category,
                            action="substitute",
                            span=cand.span,
                            confidence=cand.confidence,
                            record_ref=cand.record_ref,
                            placeholder=None,
                        )
                    )
                    continue

                start, end = cand.span
                out = out[:start] + f"<redacted:{cand.category}>" + out[end:]
                reasons.append(cand.category)
                findings.append(
                    Finding(
                        kind=cand.kind,
                        category=cand.category,
                        action="block",
                        span=cand.span,
                        confidence=cand.confidence,
                        record_ref=cand.record_ref,
                        placeholder=None,
                    )
                )

            findings.sort(key=lambda f: f.span[0])
            return ScanResult(
                text=out,
                findings=findings,
                blocked=bool(reasons),
                block_reason=(
                    "credential in response: " + ", ".join(sorted(set(reasons)))
                    if reasons
                    else None
                ),
            )
        except Exception as exc:  # pragma: no cover - defensive by design
            return ScanResult(
                text="",
                blocked=True,
                block_reason=f"scanner error, failing closed: {type(exc).__name__}: {exc}",
            )

    # -- restore -----------------------------------------------------------

    def restore(self, text: str, mapping: dict[str, str]) -> RestoreResult:
        """Put the real values back, tolerating what the model did to them.

        D15. `unrestored` is the alarm: anything placeholder-shaped still in
        the text means the round trip failed and a judge is about to see
        `[[CUST_A]]'s account`. Treat a non-empty list as a failure, not a
        warning.
        """
        if not isinstance(text, str) or not text:
            return RestoreResult(text=text if isinstance(text, str) else "")
        if not mapping:
            return RestoreResult(text=text, unrestored=find_placeholders(text))

        out = text
        restored = 0
        # Longest placeholder first: belt and braces against a shorter label
        # being a prefix of a longer one. tolerant_pattern already guards
        # this, and doing both costs nothing.
        for placeholder in sorted(mapping, key=len, reverse=True):
            out, count = tolerant_pattern(placeholder).subn(
                mapping[placeholder].replace("\\", r"\\"), out
            )
            restored += count

        return RestoreResult(text=out, restored=restored, unrestored=find_placeholders(out))

    # -- internals ---------------------------------------------------------

    def _candidates(self, text: str) -> list[_Candidate]:
        found = [
            _Candidate(
                span=hit.span,
                text=hit.text,
                category=hit.match.category,
                action="substitute",
                confidence=1.0,
                record_ref=hit.match.record_ref,
                role=hit.match.role,
                kind="known_value",
            )
            for hit in self.store.scan(text)
        ]
        found += [
            _Candidate(
                span=hit.span,
                text=hit.text,
                category=hit.category,
                action=hit.action,
                confidence=hit.confidence,
                record_ref=None,
                role="identifier",
                kind="pattern",
            )
            for hit in patterns.scan(text)
        ]
        return found

    @staticmethod
    def _reconcile(candidates: list[_Candidate]) -> list[_Candidate]:
        """Resolve overlapping spans between the two tiers.

        Known-value wins ties: it carries a record reference, so its audit
        line says "matched customer record 44219" rather than "looks like a
        card number". Blocks outrank substitutions, because refusing a
        credential costs the user nothing while missing one is permanent.
        """
        def rank(c: _Candidate) -> tuple:
            return (
                0 if c.action == "block" else 1,
                0 if c.kind == "known_value" else 1,
                -c.confidence,
                -(c.span[1] - c.span[0]),
                c.span[0],
            )

        kept: list[_Candidate] = []
        for cand in sorted(candidates, key=rank):
            if any(cand.span[0] < k.span[1] and k.span[0] < cand.span[1] for k in kept):
                continue
            kept.append(cand)
        return kept
