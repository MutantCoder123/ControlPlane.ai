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
from controlplane.cost.ledger import BudgetExceeded, CostLedger
from controlplane.cost.pricing import Usage, estimate_tokens
from controlplane.decision.tiers import (
    DecisionEngine,
    FlagBudget,
    Signal,
    signals_from_findings,
)
from controlplane.demo import events as ev
from controlplane.engine.placeholders import find_placeholders
from controlplane.engine.substitute import SubstitutionEngine
from controlplane.feedback.loop import FeedbackAggregator, ReviewQueue
from controlplane.feedback.session import SessionRiskTracker
from controlplane.metrics.registry import MetricsRegistry
from controlplane.policy.adapters import inbound_options, outbound_options
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
        #: Cumulative multi-turn / agent-step risk (D4, Phase 7). Counters
        #: only - see feedback/session.py. Budgets come from each profile's
        #: `SessionPolicy`, not from this tracker's constructor, so the same
        #: instance serves every profile with its own caps.
        self.sessions = SessionRiskTracker()

        # Every policy publish writes its own diff to the chain.
        from controlplane.audit.chain import attach_to_store

        attach_to_store(self.audit, self.store)

    # -- the pipeline ------------------------------------------------------

    async def run(
        self,
        prompt: str,
        *,
        profile_name: str | None = None,
        team: str = "support",
        session_id: str | None = None,
        agent_steps: int = 0,
        sources: str = "",
    ):
        """One request, narrated. Yields dicts from `events.EventStream`."""
        stream = ev.EventStream()
        # Prefixed, not bare hex: a bare 12-char hex id has a ~0.3% chance of
        # landing all-digits (uuid4's hex alphabet is 0-9a-f, so 10/16 per
        # char), which the audit log's own guard then refuses to write as a
        # possible card or account number (`\b\d{12,19}\b`). Flaky in tests,
        # and a live crash risk on stage. The prefix breaks the word boundary
        # the guard's pattern needs, permanently, rather than just making the
        # collision rarer.
        request_id = f"req_{uuid.uuid4().hex[:12]}"
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
        # The profile now reaches the engine (phase 2.1). It arrives as
        # `ScanOptions` rather than as a `Profile`, so `engine/` still knows
        # nothing about `policy/` - see policy/adapters.py.
        scanned = self.engine.scan_inbound(
            prompt, scope=scope, options=inbound_options(profile)
        )
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
            # phase 2.4: the profile's audit_level finally decides how much
            # decision detail the entry carries. More about the decision,
            # never more about the content.
            level=profile.audit_level,
            profile_fingerprint=profile.fingerprint,
            decision_tier=decision.tier.label,
            decision_reasons=[o.reason for o in decision.outcomes],
        )
        # Nested, not splatted: the entry has its own `seq` and it would
        # shadow the event's, which is the kind of silent collision a
        # timeline UI renders as events arriving out of order.
        yield stream.emit(ev.AUDIT_APPEND, entry=ev.audit_payload(entry))

        self.metrics.record_decision(decision, latency_ms=scan_ms)

        # -- 2b. cumulative session risk (D4) ------------------------------
        # Multi-turn and agent-step compounding, caught by counting rather
        # than by remembering. `session_id` is supplied by the caller - we
        # never mint one, because minting one would let us correlate traffic
        # we have no business correlating. No id, no tracking: an anonymous
        # request has no session to accumulate against.
        if session_id:
            verdict = self.sessions.observe(
                session_id,
                findings=scanned.findings,
                blocked=decision.blocked or scanned.blocked,
                agent_steps=agent_steps,
                max_records=profile.session.max_records_per_session,
                max_agent_steps=profile.session.max_agent_steps,
            )
            yield stream.emit(
                ev.SESSION_RISK,
                side="inside",
                **ev.session_payload(
                    session_id,
                    verdict,
                    max_records=profile.session.max_records_per_session,
                    max_agent_steps=profile.session.max_agent_steps,
                ),
            )

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

        # -- 3b. the budget gate, still before dispatch --------------------
        # `CostLedger.check_budget` existed and was tested from Phase 4, and
        # nothing on the live path ever called it (EXPLAINED 8.2). This is the
        # budget step of IDEATION section 8's pre-flight gate, finally wired.
        #
        # It sits HERE, before dispatch, for the same reason the credential
        # refusal does: you are billed the moment the model starts generating,
        # so a check that runs after dispatch has already paid for the request
        # it is about to refuse. Refusing here costs 0.00, and the event says so.
        estimate = self.ledger.estimate(
            PRICED_AS, scanned.text, profile.cost.max_output_tokens
        )
        try:
            self.ledger.check_budget(
                team=team,
                estimate=estimate,
                request_budget_usd=profile.cost.request_budget_usd,
            )
        except BudgetExceeded as exc:
            yield stream.emit(
                ev.BLOCK,
                where="budget",
                reason=str(exc),
                redacted=scanned.text,
                categories=[],
                estimate_usd=round(estimate, 6),
                cost_usd=0.0,
            )
            yield stream.emit(ev.DONE, outcome="blocked_budget")
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
        out_opts = outbound_options(profile)
        buffer = CommitPointBuffer(
            profile,
            lambda text: self.engine.scan_outbound(text, options=out_opts),
            restore=self.engine.restore,
            mapping=scanned.mapping,
        )

        raw_text = ""
        answer = ""
        unrestored: list[str] = []
        blocked_outbound = None
        # Real per-token confidence (D33), not a self-report: Ollama 0.33+
        # returns the actual log-probability it assigned each token AS IT
        # GENERATED IT. Accumulated here, in parallel with `raw_text`, and
        # handed to the quality pass below - nothing about the tested
        # commit-point buffer (D5/D6/D15) changes, this is purely additive.
        # `chunk` is a `(text, token_logprobs)` tuple from the real model;
        # test fakes yield bare strings, tolerated below, so this signal is
        # simply absent (not faked) whenever there is no real model behind it.
        logprob_trace: list[checks.TokenLogprob] = []

        try:
            async for chunk in _ollama_chunks(
                scanned.text, max_output_tokens=profile.cost.max_output_tokens
            ):
                if isinstance(chunk, tuple):
                    text, token_logprobs = chunk
                else:
                    text, token_logprobs = chunk, None
                offset = len(raw_text)
                raw_text += text
                if token_logprobs:
                    pos = offset
                    for tok in token_logprobs:
                        tok_text = tok.get("token", "")
                        logprob_trace.append(checks.TokenLogprob(
                            text=tok_text,
                            logprob=tok.get("logprob", 0.0),
                            start=pos,
                            end=pos + len(tok_text),
                        ))
                        pos += len(tok_text)
                yield stream.emit(ev.STREAM_RAW, side="outside", chunk=text)

                releases = buffer.feed(text)
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

        # -- 6b. cross-record disclosure (phase 2.2) ------------------------
        # D21's failure mode, made checkable: in a customer-facing bot the
        # catastrophic direction is outbound - customer X shown customer Y's
        # record. The comparison needs no new detection machinery, only the
        # two sets of record references we already have.
        #
        # Scanning the RESTORED answer is the point. A value we substituted
        # comes back carrying a reference that was in the request; a record
        # the model produced on its own was never a placeholder, so it
        # survives restore as literal text and the known-value store
        # recognises it. Anything in the second set but not the first crossed
        # a record boundary.
        if profile.outbound.cross_record_check and answer:
            inbound_refs = {f.record_ref for f in scanned.findings if f.record_ref}
            out_scan = self.engine.scan_outbound(answer, options=out_opts)
            crossed = sorted(
                {f.record_ref for f in out_scan.findings if f.record_ref} - inbound_refs
            )
            if crossed:
                # Irreversible: this is a disclosure, not an annotation. The
                # reader has been shown a record they did not ask about, and
                # no amount of after-the-fact marking un-shows it.
                #
                # Confidence is 1.0 because a known-value match is certain -
                # the store matched exactly - which means this clears every
                # profile's block_at and blocks on any route that runs it.
                # That is the correct outcome, not a missing nuance: the
                # profile's decision here is whether to run the check at all,
                # and softening a certain signal to produce a gentler tier
                # would be trading real protection for a talking point.
                signal = Signal(
                    category="cross_record",
                    kind="outbound",
                    confidence=1.0,
                    reversible=False,
                    evidence=(
                        f"the response references {len(crossed)} record(s) that were "
                        f"not in the request: {', '.join(crossed)}"
                    ),
                )
                outcome = self.decisions.decide([signal], profile)
                yield stream.emit(
                    ev.CROSS_RECORD,
                    side="inside",
                    crossed=crossed,
                    in_request=sorted(inbound_refs),
                    tier=outcome.tier.label,
                    evidence=signal.evidence,
                    reversible=False,
                )
                self.metrics.record_decision(outcome)
                if outcome.needs_human:
                    for item in self.queue.enqueue_decision(outcome, request_id=request_id):
                        yield stream.emit(
                            "queue.enqueue",
                            item_id=item.item_id,
                            category=item.category,
                            confidence=item.confidence,
                            reason=item.reason,
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
        async for event in self._quality_pass(
            stream, answer, prompt, profile, request_id,
            raw_text=raw_text, logprob_trace=logprob_trace, sources=sources,
        ):
            yield event

        yield stream.emit(ev.DONE, outcome="delivered")

    # -- async quality -----------------------------------------------------

    async def _quality_pass(
        self, stream, answer, prompt, profile, request_id,
        *, raw_text: str = "", logprob_trace: list[checks.TokenLogprob] | None = None,
        sources: str = "",
    ):
        """Hallucination (three claim shapes now) and toxicity; bias
        structurally elsewhere.

        Toxicity (D31) runs here unconditionally, for every profile, because
        that is the async default IDEATION 10.2 always specified - a
        profile's `toxicity_sync` flag is not read by this pass. See D31:
        the severe-category synchronous exception stays unbuilt, so a
        profile that sets `toxicity_sync: true` gets the same async check as
        one that doesn't, today.

        `has_checkable_claims` gates ONLY entity_not_in_source, not this whole
        method. That check's entire premise is "a number or a proper noun
        with no provenance" - an answer with neither has nothing for it to
        find. Toxicity has no such premise: "your staff are incompetent
        morons" contains no number, date or proper noun, so gating toxicity
        behind the same filter would mean the check we just built never runs
        on the exact kind of sentence it exists to catch. Caught while wiring
        this in, before it shipped silently broken. The two new claim-shape
        checks (D33) have the same property - overclaiming and unsupported
        causal language need no entity either - so they run unconditionally
        too, alongside toxicity.

        `raw_text`/`logprob_trace` (D33) are threaded through to every check
        so each can sharpen its own confidence from the model's REAL
        per-token probability, when the running backend provides one -
        never a self-report, and never required (every check degrades to
        its base formula without them).
        """
        ran: list[str] = []
        findings: list[tuple[checks.QualityFinding, str]] = []

        if checks.has_checkable_claims(answer):
            ran.append("entity_not_in_source")
            findings += [
                (f, "hallucination")
                for f in checks.entity_not_in_source(
                    answer, prompt, sources,
                    logprob_trace=logprob_trace, raw_text=raw_text,
                )
            ]

        ran += ["overclaim", "unsupported_causal_claim", "toxicity"]
        findings += [
            (f, "overclaim")
            for f in checks.find_absolute_claims(
                answer, logprob_trace=logprob_trace, raw_text=raw_text,
            )
        ]
        findings += [
            (f, "hallucination")
            for f in checks.find_unsupported_causal_claims(
                answer, prompt, sources,
                logprob_trace=logprob_trace, raw_text=raw_text,
            )
        ]
        findings += [(f, "toxicity") for f in checks.toxicity(answer)]

        for finding, category in findings:
            signal = finding.to_signal(category=category)
            outcome = self.decisions.decide([signal], profile)
            yield stream.emit(
                ev.QUALITY_FINDING,
                side="inside",
                check=finding.check,
                category=category,
                detail=finding.detail,
                evidence=finding.evidence,
                confidence=round(finding.confidence, 3),
                # Shown so the number is auditable rather than oracular.
                confidence_formula=finding.formula,
                # Character offsets into `answer` (D33) - lets the dashboard
                # highlight the exact flagged substring instead of only
                # listing it below the response. None for whole-response
                # findings (toxicity has no single span).
                span=list(finding.span) if finding.span else None,
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

        skipped = (
            None if "entity_not_in_source" in ran
            else "entity_not_in_source: no numbers, dates or proper nouns - nothing to check"
        )
        yield stream.emit(
            ev.QUALITY_DONE,
            ran=ran,
            skipped=skipped,
            # phase 2.5: `sources` was hardcoded empty, so an answer was only
            # ever judged against the question. A correct-but-new fact was
            # indistinguishable from an invented one - the largest single
            # source of false positives in this check. Reported so the reader
            # knows which of the two comparisons they are looking at.
            grounded_against=("question + sources" if sources else "question only"),
            sources_chars=len(sources or ""),
            not_built={
                "toxicity_sync_exception": "D31 - the 'small set of severe "
                                           "categories block synchronously' "
                                           "exception in IDEATION 10.2 is not "
                                           "implemented; toxicity always runs "
                                           "here, async, regardless of a "
                                           "profile's toxicity_sync flag",
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


async def _ollama_chunks(prompt: str, *, max_output_tokens: int | None = None):
    """Raw token chunks from the local model, paired with the REAL
    log-probability the model assigned each one as it generated it.

    Yields `(text, token_logprobs)` - `token_logprobs` is Ollama's own
    `logprobs` list for this delta (D33), or `None` if the running server
    predates 0.33 / doesn't expose it, in which case every downstream
    consumer degrades gracefully to the pre-D33 behaviour rather than
    crashing on a missing field.

    Kept behind a generator so the pipeline above has no HTTP in it and can be
    driven by a fake in tests - the same reason TRACK-B.md puts the provider
    behind a small interface. Test fakes yield bare strings, not tuples; the
    orchestrator tolerates both (see `run()`), so this is additive, not a
    breaking change to the harness.
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
        # `num_predict` is Ollama's generation cap, verified to stop at
        # exactly the limit with done_reason "length". This is the profile's
        # `cost.max_output_tokens` finally doing something (phase 2.3) - a
        # ceiling declared in policy and previously read by nobody.
        "options": {
            "temperature": 0.2,
            "seed": 20260830,
            **({"num_predict": max_output_tokens} if max_output_tokens else {}),
        },
        "logprobs": True,
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
                    yield text, data.get("logprobs")
                if data.get("done"):
                    return
