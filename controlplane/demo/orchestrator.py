"""The demo pipeline: real modules, one event stream, nothing re-implemented.

This is P14's surface over the nine packages Phase 1-5 built. Every stage
below calls the module that owns it - `SubstitutionEngine`, `DecisionEngine`,
`CommitPointBuffer`, `AuditLog`, `CostLedger`, `MetricsRegistry`,
`ReviewQueue`, `quality.checks` - and emits what it returned.

THE ORDERING IS THE ARGUMENT (IDEATION section 8)
-------------------------------------------------
    scan -> decide -> (refuse at 0.00, never dispatch) -> dispatch -> restore

You are billed the moment tokens are generated. Forwarding first and
cancelling on failure blocks the request AND pays for it, which is how a
safety feature quietly contradicts the cost pillar. Check first, dispatch
second. The `cost_usd: 0.0` on a block event is that argument, on screen.

WHY THERE IS A `demo/` LANE AT ALL
----------------------------------
`gateway/` is Track B's, and their FastAPI spine is the OpenAI-compatible
integration claim - `/v1/chat/completions` with an unmodified client. This
package is a different thing: an instrumented narration of the same pipeline,
for the video. Putting it here keeps their file theirs (CONTRACTS section 1)
and keeps the wire-compatible route free of demo-only event plumbing.
"""

from __future__ import annotations

import time
import uuid
from pathlib import Path

import httpx

from controlplane.audit.chain import AuditLog, record_scan, text_fingerprint
from controlplane.cost.ledger import CostLedger
from controlplane.cost.pricing import Usage, estimate_tokens
from controlplane.decision.tiers import (
    DecisionEngine,
    FlagBudget,
    signals_from_findings,
)
from controlplane.demo import events as ev
from controlplane.engine.placeholders import find_placeholders
from controlplane.engine.substitute import SubstitutionEngine
from controlplane.feedback.loop import FeedbackAggregator, ReviewQueue
from controlplane.metrics.registry import MetricsRegistry
from controlplane.policy.store import ControlPlane
from controlplane.quality import checks
from controlplane.stream.buffer import CommitPointBuffer

DEMO_RECORDS = Path(__file__).resolve().parent / "data" / "demo_records.jsonl"

OLLAMA_URL = "http://127.0.0.1:11434/api/generate"
OLLAMA_MODEL = "llama3.2:1b"

#: The demo serves from a local model so it runs with no key and no network,
#: but the cost pillar is about what a real provider would have charged. We
#: price the request against the model a governed route would actually use and
#: say so in the payload - a cost number whose provenance is hidden is exactly
#: the kind of claim D7 exists to stop us making.
PRICED_AS = "claude-haiku-4-5"
BASELINE = "claude-opus-5"


class DemoRuntime:
    """Long-lived state for the demo server.

    STATELESSNESS CHECK (IDEATION section 3): every object held here is
    aggregate or references-only. The audit log stores fingerprints and record
    refs, the ledger stores token counts and prefix hashes, the registry
    stores counters. No prompt, no response, and no mapping outlives the
    request that created it - `RequestScope` is created per call below and
    dropped when the generator finishes.
    """

    def __init__(self, records_path: str | Path = DEMO_RECORDS) -> None:
        self.engine = SubstitutionEngine(str(records_path))
        self.control = ControlPlane()
        self.store = self.control.store(default_profile="internal-knowledge")
        self.decisions = DecisionEngine(FlagBudget(window=100))
        self.audit = AuditLog()
        self.ledger = CostLedger(baseline_model=BASELINE)
        self.metrics = MetricsRegistry()
        self.queue = ReviewQueue()
        self.feedback = FeedbackAggregator()

        # Every policy publish writes its own diff to the chain.
        from controlplane.audit.chain import attach_to_store

        attach_to_store(self.audit, self.store)

    # -- the pipeline ------------------------------------------------------

    async def run(self, prompt: str, *, profile_name: str | None = None, team: str = "support"):
        """One request, narrated. Yields dicts from `events.EventStream`."""
        stream = ev.EventStream()
        request_id = uuid.uuid4().hex[:12]
        profile = self.store.profile_for(profile_name)

        yield stream.emit(
            ev.REQUEST_OPEN,
            request_id=request_id,
            profile=profile.name,
            fingerprint=profile.fingerprint,
            policy_version=self.store.version,
            description=profile.description,
            streaming={
                "mode": profile.streaming.mode,
                "buffered": profile.streaming.buffered,
                "commit_tokens": profile.streaming.commit_tokens,
                "commit_ms": profile.streaming.commit_ms,
                "overlap_chars": profile.streaming.overlap_chars,
            },
            thresholds={
                "block_at": profile.decision.block_at,
                "review_band": list(profile.decision.review_band),
                "flag_budget_per_100": profile.decision.flag_budget_per_100,
                "always_review": profile.decision.always_review,
            },
            served_by=f"{OLLAMA_MODEL} (local)",
            priced_as=PRICED_AS,
        )

        # -- 1. inbound scan ----------------------------------------------
        scope = self.engine.new_request_scope()
        t0 = time.perf_counter()
        scanned = self.engine.scan_inbound(prompt, scope=scope)
        scan_ms = round((time.perf_counter() - t0) * 1000, 2)

        yield stream.emit(
            ev.SCAN_INBOUND,
            side="inside",
            original=prompt,
            substituted=scanned.text,
            findings=[ev.finding_payload(f) for f in scanned.findings],
            mapping=scanned.mapping,
            blocked=scanned.blocked,
            block_reason=scanned.block_reason,
            scan_ms=scan_ms,
        )

        # -- 2. decision ---------------------------------------------------
        signals = signals_from_findings(scanned.findings)
        decision = self.decisions.decide(
            signals, profile, policy_version=self.store.version
        )
        yield stream.emit(ev.DECISION, **ev.decision_payload(decision))

        entry = record_scan(
            self.audit,
            request_id=request_id,
            profile=profile.name,
            policy_version=self.store.version,
            findings=scanned.findings,
            prompt_fingerprint=text_fingerprint(prompt),
            blocked=decision.blocked or scanned.blocked,
        )
        # Nested, not splatted: the entry has its own `seq` and it would
        # shadow the event's, which is the kind of silent collision a
        # timeline UI renders as events arriving out of order.
        yield stream.emit(ev.AUDIT_APPEND, entry=ev.audit_payload(entry))

        self.metrics.record_decision(decision, latency_ms=scan_ms)

        if decision.needs_human:
            for item in self.queue.enqueue_decision(decision, request_id=request_id):
                yield stream.emit(
                    "queue.enqueue",
                    item_id=item.item_id,
                    category=item.category,
                    confidence=item.confidence,
                    reason=item.reason,
                )

        # -- 3. refuse before dispatch ------------------------------------
        if decision.blocked or scanned.blocked:
            yield stream.emit(
                ev.BLOCK,
                where="inbound",
                reason=scanned.block_reason or "blocked by decision engine",
                redacted=scanned.text,
                categories=[f.category for f in scanned.findings if f.action == "block"],
                # Nothing was generated, so nothing was billed. This number is
                # the ordering argument in IDEATION section 8, made concrete.
                cost_usd=0.0,
            )
            yield stream.emit(ev.DONE, outcome="blocked")
            return

        # -- 4. leak check, then dispatch ---------------------------------
        leaked = [v for v in scanned.mapping.values() if v and v in scanned.text]
        yield stream.emit(
            ev.DISPATCH,
            side="outside",
            text=scanned.text,
            leak_check={
                "checked": len(scanned.mapping),
                "leaked": leaked,
                "ok": not leaked,
            },
            model=OLLAMA_MODEL,
            input_tokens=estimate_tokens(scanned.text),
        )

        # -- 5. stream, buffered by the REAL commit-point buffer ----------
        buffer = CommitPointBuffer(
            profile,
            self.engine.scan_outbound,
            restore=self.engine.restore,
            mapping=scanned.mapping,
        )

        raw_text = ""
        answer = ""
        unrestored: list[str] = []
        blocked_outbound = None

        try:
            async for chunk in _ollama_chunks(scanned.text):
                raw_text += chunk
                yield stream.emit(ev.STREAM_RAW, side="outside", chunk=chunk)

                releases = buffer.feed(chunk)
                if not releases:
                    yield stream.emit(
                        ev.BUFFER_HOLD,
                        side="outside",
                        pending_chars=buffer.pending_chars,
                        held_chars=buffer.held_chars,
                        why="no commit point reached",
                    )
                    continue

                for release in releases:
                    if release.blocked:
                        blocked_outbound = release.reason
                        break
                    answer += release.text
                    restored = _count_restored(release.text, scanned.mapping)
                    yield stream.emit(
                        ev.BUFFER_RELEASE,
                        side="inside",
                        text=release.text,
                        trigger=release.trigger,
                        held_chars=buffer.held_chars,
                        commits=buffer.stats.commits,
                        ttfb_ms=buffer.stats.ttfb_ms,
                        restored=restored,
                    )
                if blocked_outbound:
                    break

            if not blocked_outbound:
                for release in buffer.flush():
                    if release.blocked:
                        blocked_outbound = release.reason
                        break
                    answer += release.text
                    yield stream.emit(
                        ev.BUFFER_RELEASE,
                        side="inside",
                        text=release.text,
                        trigger=release.trigger,
                        held_chars=buffer.held_chars,
                        commits=buffer.stats.commits,
                        ttfb_ms=buffer.stats.ttfb_ms,
                        restored=_count_restored(release.text, scanned.mapping),
                    )

        except httpx.HTTPError as exc:
            yield stream.emit(
                ev.ERROR,
                reason=f"cannot reach the local model at {OLLAMA_URL}: {exc}",
                hint="start it with `ollama serve`, then `ollama pull llama3.2:1b`",
            )
            return

        if blocked_outbound:
            yield stream.emit(
                ev.BLOCK,
                where="outbound",
                reason=blocked_outbound,
                released_so_far=len(answer),
                # The half-sentence carrying it was never released, because the
                # buffer holds text until it has been scanned as one piece with
                # what follows (D5). A kill switch after render is theatre.
                cost_usd=round(self.ledger.prices.cost(
                    Usage(PRICED_AS, estimate_tokens(scanned.text), estimate_tokens(raw_text))
                ), 6),
            )
            yield stream.emit(ev.DONE, outcome="blocked_outbound")
            return

        # -- 6. delivered --------------------------------------------------
        # `restored` is informational: how many placeholder instances existed
        # in the full, clean text. It is NOT the alarm - restoring a fresh
        # copy of `raw_text` always succeeds, because `raw_text` always holds
        # every placeholder whole. It cannot tell you whether the STREAMED
        # copy the reader actually saw came out the same way.
        restored_count = self.engine.restore(raw_text, scanned.mapping).restored

        # D15's alarm, checked against `answer` - the text assembled commit
        # by commit, exactly as delivered. A placeholder bisected by a commit
        # boundary (see stream/buffer.py) would be invisible to a check
        # against `raw_text`, because `raw_text` was never bisected. Checking
        # the thing that was actually rendered is the whole point of an
        # alarm: non-empty here means a judge is about to see `[[CUST_A`
        # on stage, and the previous version of this check could not detect
        # that even while it was happening.
        unrestored = find_placeholders(answer)
        yield stream.emit(
            ev.ANSWER_DONE,
            side="inside",
            answer=answer,
            raw=raw_text,
            restored=restored_count,
            unrestored=unrestored,
            ttfb_ms=buffer.stats.ttfb_ms,
            commits=buffer.stats.commits,
            released_chars=buffer.stats.released_chars,
        )

        # -- 7. cost -------------------------------------------------------
        usage = Usage(
            model=PRICED_AS,
            input_tokens=estimate_tokens(scanned.text),
            output_tokens=estimate_tokens(raw_text),
        )
        led = self.ledger.record(
            request_id=request_id,
            team=team,
            profile=profile.name,
            usage=usage,
            prompt_prefix=scanned.text,
        )
        yield stream.emit(
            ev.COST,
            request_usd=round(led.cost_usd, 6),
            baseline_usd=round(led.baseline_cost_usd, 6),
            model=PRICED_AS,
            baseline_model=BASELINE,
            served_by=f"{OLLAMA_MODEL} (local, $0.00)",
            note="priced against published rates; the take runs on a local model",
            # Nested for the same reason the audit entry is: `as_dict()` has
            # its own `baseline_model` key and splatting it collides.
            running_total=self.ledger.savings().as_dict(),
        )

        # -- 8. the reversible half, AFTER delivery ------------------------
        # IDEATION section 6. These run here, not before, and the t_ms on
        # these events is the proof: the reader already had their answer.
        async for event in self._quality_pass(stream, answer, prompt, profile, request_id):
            yield event

        yield stream.emit(ev.DONE, outcome="delivered")

    # -- async quality -----------------------------------------------------

    async def _quality_pass(self, stream, answer, prompt, profile, request_id):
        """Hallucination now; toxicity labelled, bias structurally elsewhere."""
        if not checks.has_checkable_claims(answer):
            yield stream.emit(
                ev.QUALITY_DONE,
                ran=[],
                skipped="no numbers, dates or proper nouns - nothing to check",
            )
            return

        findings = checks.entity_not_in_source(answer, prompt, sources="")
        signals = [f.to_signal() for f in findings]

        for finding, signal in zip(findings, signals):
            outcome = self.decisions.decide([signal], profile)
            yield stream.emit(
                ev.QUALITY_FINDING,
                side="inside",
                check=finding.check,
                detail=finding.detail,
                evidence=finding.evidence,
                confidence=round(finding.confidence, 3),
                # Shown so the number is auditable rather than oracular.
                confidence_formula="min(0.9, 0.55 + 0.1 x entities_without_provenance)",
                tier=outcome.tier.label,
                reversible=True,
            )
            self.metrics.record_decision(outcome)

            # The queue's real source of work. Inbound findings almost never
            # reach it now that substitution counts as mitigation, which is
            # correct - there is nothing for a human to decide about a value
            # the provider never saw. What DOES need a person is a reversible
            # finding on a route whose profile says so: `decision-support` is
            # EU AI Act high-risk, and it reviews every response because the
            # legal exposure justifies the cost, not because we are unsure.
            if outcome.needs_human:
                for item in self.queue.enqueue_decision(outcome, request_id=request_id):
                    yield stream.emit(
                        "queue.enqueue",
                        item_id=item.item_id,
                        category=item.category,
                        confidence=item.confidence,
                        reason=item.reason,
                    )

        yield stream.emit(
            ev.QUALITY_DONE,
            ran=["entity_not_in_source"],
            not_built={
                "toxicity": "off-the-shelf classifier in production; on the "
                            "do-not-build list here (D23-labelled, not omitted)",
                "consistency_sampling": "D11 - sampling only detects RANDOM "
                                        "fabrication, and scores systematic "
                                        "failure as reliable",
                "bias": "D12 - bias is a property of a distribution. There is "
                        "no per-response score to compute. See /trust.",
            },
            findings=len(findings),
        )


def _count_restored(text: str, mapping: dict[str, str]) -> int:
    return sum(1 for value in mapping.values() if value and value in text)


async def _ollama_chunks(prompt: str):
    """Raw token chunks from the local model.

    Kept behind a generator so the pipeline above has no HTTP in it and can be
    driven by a fake in tests - the same reason TRACK-B.md puts the provider
    behind a small interface.
    """
    import json as _json

    # Fixed seed and low temperature. WORKFLOW section 7: a demo has to
    # reproduce from a clean checkout, and "it worked when I recorded it"
    # is how a live take goes wrong. The model still generates - this only
    # removes the variance we have no reason to want.
    payload = {
        "model": OLLAMA_MODEL,
        "prompt": prompt,
        "stream": True,
        "options": {"temperature": 0.2, "seed": 20260830},
    }
    async with httpx.AsyncClient(timeout=httpx.Timeout(120.0, connect=5.0)) as client:
        async with client.stream("POST", OLLAMA_URL, json=payload) as response:
            response.raise_for_status()
            async for line in response.aiter_lines():
                if not line:
                    continue
                data = _json.loads(line)
                text = data.get("response", "")
                if text:
                    yield text
                if data.get("done"):
                    return
