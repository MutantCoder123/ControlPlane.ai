"""FastAPI surface for the demo dashboard.

One streaming route for the request pipeline, and a small set of control
routes for the things the video needs to *do* rather than watch: swap a
profile, verify the audit chain, tamper with it, resolve a review item, run a
canary sweep, run a bias probe.

Nothing here computes anything. Every handler calls the module that owns the
answer and returns what it said.

Run it:
    python -m controlplane.demo.server
"""

from __future__ import annotations

import asyncio

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from controlplane.demo import events as ev
from controlplane.demo.orchestrator import (
    BASELINE,
    OLLAMA_MODEL,
    PRICED_AS,
    DemoRuntime,
    _ollama_chunks,
)
from controlplane.feedback.loop import PolicyTuner, Verdict, close_loop
from controlplane.metrics.canary import CanarySuite
from controlplane.policy import enforcement
from controlplane.quality.checks import (
    NoSubjectToVary,
    OutcomeDistribution,
    build_variants,
    classify_forced_choice,
    find_subject,
    parse_forced_choice,
)

app = FastAPI(title="ControlPlane demo")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],          # local demo only
    allow_methods=["*"],
    allow_headers=["*"],
)

runtime = DemoRuntime()

#: The jurisdiction floor currently in force, if any (Phase 7). Demo-server
#: state, not runtime state - `ControlPlane.compile_bundle` is stateless with
#: respect to it, so this is just what the LAST publish asked for, kept so a
#: subsequent policy patch recompiles under the same floor rather than
#: silently dropping it.
current_jurisdiction: str | None = None


# --------------------------------------------------------------------------
# The pipeline
# --------------------------------------------------------------------------

class RunRequest(BaseModel):
    prompt: str
    profile: str | None = None
    team: str = "support"
    #: Supplied by the caller, never minted here - see orchestrator.py's note
    #: on why we do not generate our own session ids.
    session_id: str | None = None
    agent_steps: int = 0
    #: Reference material the answer is allowed to draw on - a retrieved
    #: document, a policy extract, a case file. Without it the hallucination
    #: check can only compare the answer against the question, so anything
    #: correct but new reads as invented (phase 2.5).
    sources: str = ""


@app.post("/demo/run")
async def run(req: RunRequest):
    async def frames():
        try:
            async for event in runtime.run(
                req.prompt,
                profile_name=req.profile,
                team=req.team,
                session_id=req.session_id,
                agent_steps=req.agent_steps,
                sources=req.sources,
            ):
                yield ev.EventStream.sse(event)
        except Exception as exc:                      # noqa: BLE001 - demo surface
            yield ev.EventStream.sse(
                {"seq": -1, "t_ms": 0, "stage": ev.ERROR, "side": "meta", "reason": str(exc)}
            )

    return StreamingResponse(
        frames(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


#: The demo cut, in order. D22: ten minutes against nine steps is about forty
#: seconds each with no slack, so the prompts are canned and the operator
#: presses a button rather than typing on the take.
#:
#: The framing is deliberate and was arrived at by testing. A 1B local model
#: refuses "tell the customer their refund amount" as financial advice, and a
#: refusal is a dull forty seconds of video. Framed as a rewrite task with a
#: do-not-invent instruction it answers every time - and that instruction is
#: also what makes the hallucination check on the far side meaningful.
PRESETS = [
    {
        "id": "round-trip",
        "title": "The round trip",
        "proves": "Substitution, not redaction - and the operand survives it",
        "profile": "internal-knowledge",
        "prompt": (
            "Rewrite the notes below as a short customer email. Do not add "
            "any facts that are not in the notes.\n\n"
            "Notes:\n"
            "- Customer: Priya Sharma\n"
            "- Account balance: 45230 rupees\n"
            "- Refund approved: 12 percent of the balance\n"
            "- Receipt already emailed to priya.sharma@example.com\n\n"
            "Email:"
        ),
        "watch": "45230 crosses the line untouched. The name and the email do not. "
                 "That is D16: substitute identifiers, never operands.",
    },
    {
        "id": "credential",
        "title": "The credential",
        "proves": "Refusal happens before dispatch, so it costs $0.00",
        "profile": "internal-knowledge",
        "prompt": (
            "Here is our production key sk-abcdefghij0123456789ABCDEFGHIJ - "
            "write a curl command that uses it to list the customer index."
        ),
        "watch": "The token stops at the boundary. Nothing was generated, so "
                 "nothing was billed. Forwarding first and cancelling would "
                 "have blocked the request AND paid for it.",
    },
    {
        "id": "landmine",
        "title": "The landmine",
        "proves": "Known-value matching beats regex",
        "profile": "internal-knowledge",
        "prompt": (
            "Two cards came in on the same batch: 4111 1111 1111 1111 and "
            "5425233430109903. Which one belongs to a customer on file?"
        ),
        "watch": "Both pass the Luhn check. Only one is ours. A regex flags "
                 "both; we flag the one that matches a record, and the audit "
                 "line says which record.",
    },
    {
        "id": "ungoverned",
        "title": "The edge of governance",
        "proves": "Coverage degrades gracefully instead of falling to zero",
        "profile": "internal-knowledge",
        "prompt": (
            "Summarise this note for the file: Meera Nair called about card "
            "4539578763621486 and asked us to check the balance."
        ),
        "watch": "Meera Nair is in an UNGOVERNED source, so the name is not in "
                 "the known-value store and stays. The card still goes, on the "
                 "checksum tier - but with no record_ref, so the audit line is "
                 "weaker. That is D28, shown rather than claimed.",
    },
    {
        "id": "public-facing",
        "title": "The same finding, a stricter route",
        "proves": "Route profiles are load-bearing, not decoration",
        "profile": "customer-support",
        "prompt": (
            "Rewrite the notes below as a short customer email. Do not add "
            "any facts that are not in the notes.\n\n"
            "Notes:\n"
            "- Customer: Priya Sharma\n"
            "- Account balance: 45230 rupees\n"
            "- Refund approved: 12 percent of the balance\n"
            "- Receipt already emailed to priya.sharma@example.com\n\n"
            "Email:"
        ),
        "watch": "Identical prompt, identical findings, different route. The "
                 "tier is a function of severity x confidence x PROFILE, never "
                 "the finding alone.",
    },
    {
        "id": "session-sprawl",
        "title": "No single turn looks wrong",
        "proves": "Compounding risk across turns, caught without storing a prompt",
        "profile": "internal-knowledge",
        # A SEQUENCE, not one prompt - the frontend fires these in order on one
        # session id. `internal-knowledge` caps at 3 distinct records per
        # session (Phase 7), small on purpose so the fourth, ordinary-looking
        # request is the one that trips it.
        #
        # Each prompt is fully self-contained on purpose, not "now do the same
        # for X": every request really is independent and stateless - we send
        # no prior turns to the model - so a prompt that only makes sense with
        # memory of the last one gets a confused answer, which looked like a
        # bug on stage before this fix. Same phrasing each time, only the name
        # changes, which is itself the point: nothing about any one request
        # is different, only the session accumulating underneath it.
        "prompts": [
            "Internal note: Priya Sharma called to confirm her contact "
            "details are up to date. Write one sentence for the file "
            "confirming the note was reviewed.",
            "Internal note: Rajesh Kumar called to confirm his contact "
            "details are up to date. Write one sentence for the file "
            "confirming the note was reviewed.",
            "Internal note: Kavya Reddy called to confirm her contact "
            "details are up to date. Write one sentence for the file "
            "confirming the note was reviewed.",
            "Internal note: Anita Desai called to confirm her contact "
            "details are up to date. Write one sentence for the file "
            "confirming the note was reviewed.",
        ],
        "watch": "Each request alone is unremarkable - one customer, one lookup. "
                 "The session panel counts distinct customers touched, not what "
                 "was said, and the fourth trips the budget: multi-turn "
                 "compounding, caught with counters instead of a transcript.",
    },
    {
        "id": "toxic-vent",
        "title": "The internal vent",
        "proves": "Toxicity is checked too - off the hot path, not skipped (D31)",
        "profile": "customer-support",
        "prompt": (
            "Write one short, casual internal Slack message venting about the "
            "ticketing software crashing for the third time today. Use the "
            "word stupid naturally, like a real annoyed coworker would.\n\n"
            "Message:"
        ),
        "watch": "The reply streams and delivers normally - toxicity is "
                 "reversible harm, so it is never a reason to hold the "
                 "response. The finding shows up in 'After delivery', with a "
                 "real classifier score, after the reader already has the "
                 "message. Notice which profile this is: customer-support "
                 "declares toxicity_sync in its policy, but the check still "
                 "ran async - that flag isn't wired to anything yet (D31), "
                 "and the honest gap is right there in the not_built list.",
    },
    {
        "id": "grounded",
        "title": "Judged against the document",
        "proves": "The same answer, with and without the source it should have used",
        "profile": "internal-knowledge",
        "prompt": "What is our refund window, and what happens after it closes?",
        "sources": (
            "Refund policy, section 4. Customers may request a full refund "
            "within 30 days of purchase. After 30 days, requests are handled "
            "as store credit at the discretion of the support lead."
        ),
        "watch": "Run it once as-is: the answer is judged against the QUESTION "
                 "only, so '30 days' and 'store credit' look invented - they "
                 "appear nowhere in what was asked. Now clear the reference "
                 "box and run again, or paste the policy back in. Same answer, "
                 "different verdict. Until phase 2.5 `sources` was hardcoded "
                 "empty, so every correct-but-new fact read as a fabrication: "
                 "the single largest source of false positives in this check.",
    },
    {
        "id": "invented-reason",
        "title": "The invented reason",
        "proves": "Hallucination beyond numbers - and REAL confidence, not a self-report (D33)",
        "profile": "internal-knowledge",
        "prompt": (
            "Write a two-sentence internal Slack update about a delayed "
            "shipment (order value 4500 rupees), casually mentioning what "
            "probably caused the delay.\n\nUpdate:"
        ),
        "watch": "Nothing here says WHY the shipment was delayed - watch the "
                 "model invent a plausible-sounding cause anyway ('unforeseen "
                 "issues with our supplier's shipping process'). The "
                 "highlighted span in 'What you read' is the exact invented "
                 "phrase, and the confidence next to it comes from the "
                 "model's own real per-token probability as it generated "
                 "those words - not a self-report, and not the old flat "
                 "formula. This is a hallucination with no number or name in "
                 "it at all, which the entity check alone would have missed.",
    },
]


@app.get("/demo/presets")
async def presets():
    return {"presets": PRESETS}


@app.get("/demo/health")
async def health():
    """Whether the demo can actually run, and if not, what to fix.

    An empty screen on the take is the worst possible failure, so this reports
    the local model's reachability rather than letting the first request
    discover it.
    """
    model_ok, detail = True, "reachable"
    try:
        async for _ in _ollama_chunks("hi"):
            break
    except Exception as exc:                          # noqa: BLE001
        model_ok, detail = False, str(exc)

    return {
        "ok": model_ok,
        "model": {"name": OLLAMA_MODEL, "reachable": model_ok, "detail": detail},
        "records": len(runtime.engine._store) if hasattr(runtime.engine, "_store") else None,
        "profiles": runtime.store.bundle.names,
        "policy_version": runtime.store.version,
        "priced_as": PRICED_AS,
        "baseline_model": BASELINE,
    }


# --------------------------------------------------------------------------
# Policy - demo step 4 and 7
# --------------------------------------------------------------------------

@app.get("/demo/profiles")
async def profiles():
    bundle = runtime.store.bundle
    out = []
    for name in bundle.names:
        p = bundle.get(name)
        out.append({
            "name": p.name,
            "description": p.description,
            "fingerprint": p.fingerprint,
            "geography": p.geography,
            "decision": {
                "block_at": p.decision.block_at,
                "review_band": list(p.decision.review_band),
                "flag_budget_per_100": p.decision.flag_budget_per_100,
                "always_review": p.decision.always_review,
                "exempt": list(p.decision.exempt),
            },
            "streaming": {
                "mode": p.streaming.mode,
                "buffered": p.streaming.buffered,
                "commit_tokens": p.streaming.commit_tokens,
                "commit_ms": p.streaming.commit_ms,
                "overlap_chars": p.streaming.overlap_chars,
            },
            "quality": {
                "hallucination_tier": p.quality.hallucination_tier,
                "toxicity_sync": p.quality.toxicity_sync,
            },
            "inbound": {
                "substitute_pii": p.inbound.substitute_pii,
                "known_value_matching": p.inbound.known_value_matching,
            },
            "session": {
                "max_records_per_session": p.session.max_records_per_session,
                "max_agent_steps": p.session.max_agent_steps,
            },
            "audit_level": p.audit_level,
        })
    return {
        "version": runtime.store.version,
        "jurisdiction": current_jurisdiction,
        "profiles": out,
        # Which of these settings actually change behaviour, and which are
        # declared only (policy/enforcement.py). An audit on 2026-09-02 found
        # six fields on this page that nothing read, and a viewer had no way
        # to tell them from the ones that worked. Now the page can say so, and
        # a test fails the build if a new field arrives undeclared.
        "enforcement": enforcement.as_payload(),
    }


class PatchRequest(BaseModel):
    profile: str
    section: str
    key: str
    value: object


@app.post("/demo/policy/patch")
async def patch_policy(req: PatchRequest):
    """Author a change centrally, recompile, publish. The data plane just reads.

    This is the control-plane / data-plane split (IDEATION section 16) as a
    button: nothing on the hot path is asked to re-read a file or make a
    network call, and the response carries the fingerprint change plus the
    readable diff that explains why the next request behaves differently.
    """
    before = runtime.store.bundle.get(req.profile)
    if before is None:
        raise HTTPException(404, f"no profile {req.profile!r}")

    try:
        bundle = runtime.control.compile_bundle(
            overrides={req.profile: {req.section: {req.key: req.value}}},
            jurisdiction=current_jurisdiction,
        )
    except Exception as exc:                          # noqa: BLE001
        # A bad policy fails when it is authored, never when a request hits
        # it. Surfacing the compiler's own message is the point.
        raise HTTPException(400, str(exc)) from exc

    runtime.store.publish(bundle)
    after = bundle.get(req.profile)
    return {
        "version": runtime.store.version,
        "profile": req.profile,
        "fingerprint": {"before": before.fingerprint, "after": after.fingerprint},
        "diff": {k: [str(v[0]), str(v[1])] for k, v in after.diff(before).items()},
    }


# --------------------------------------------------------------------------
# Jurisdiction (Phase 7) - a floor every profile is clamped against, never
# a ceiling. "Regulatory expectations differ by geography and industry...
# and continue to evolve, so rigid, hard-coded rules age quickly" (brief).
# --------------------------------------------------------------------------

@app.get("/demo/jurisdictions")
async def jurisdictions():
    return {
        "current": current_jurisdiction,
        "options": [runtime.control.jurisdiction_info(c) for c in runtime.control.list_jurisdictions()],
    }


class JurisdictionRequest(BaseModel):
    code: str | None = None  # null clears the floor entirely


@app.post("/demo/jurisdiction")
async def set_jurisdiction(req: JurisdictionRequest):
    """Publish every profile clamped to a jurisdiction's floor, and show
    exactly what moved.

    Compiles TWICE - once plain, once under the floor - and diffs the two,
    rather than adding a field to `Profile` to record it. That keeps the
    dataclass and its fingerprint clean, and it is free: this is the control
    plane, off the hot path, which is the entire point of the split (D20).
    """
    global current_jurisdiction

    try:
        plain = runtime.control.compile_bundle()
        floored = runtime.control.compile_bundle(jurisdiction=req.code)
    except Exception as exc:                          # noqa: BLE001
        raise HTTPException(400, str(exc)) from exc

    runtime.store.publish(floored)
    current_jurisdiction = req.code

    per_profile = {}
    for name in floored.names:
        diff = floored.get(name).diff(plain.get(name))
        per_profile[name] = {
            "fingerprint": {"before": plain.get(name).fingerprint, "after": floored.get(name).fingerprint},
            "clamped": {k: [str(v[0]), str(v[1])] for k, v in diff.items()},
        }

    return {
        "version": runtime.store.version,
        "jurisdiction": req.code,
        "profiles": per_profile,
    }


# --------------------------------------------------------------------------
# Audit - demo step 6
# --------------------------------------------------------------------------

@app.get("/demo/audit")
async def audit():
    return {
        "head": runtime.audit.head,
        "length": len(runtime.audit),
        "entries": [ev.audit_payload(e) for e in runtime.audit.entries],
    }


@app.post("/demo/audit/verify")
async def audit_verify():
    result = runtime.audit.verify()
    return {
        "ok": bool(result),
        "entries": result.entries,
        "broken_at": result.broken_at,
        "reason": result.reason,
        "claim": "tamper-evident, not tamper-proof - an attacker with process "
                 "access can still append. What they cannot do is edit history "
                 "without every later hash disagreeing (D14).",
    }


class TamperRequest(BaseModel):
    seq: int
    event: str = "scan"


@app.post("/demo/audit/tamper")
async def audit_tamper(req: TamperRequest):
    """Edit a committed entry in place, leaving its hash alone.

    The only mutation path into the log, underscore-private, and it exists so
    the claim can be falsified on camera instead of asserted. Verify before,
    tamper, verify after.
    """
    if not 0 <= req.seq < len(runtime.audit):
        raise HTTPException(404, f"no entry {req.seq}")
    runtime.audit._tamper(req.seq, event=req.event)
    result = runtime.audit.verify()
    return {
        "tampered_seq": req.seq,
        "ok": bool(result),
        "broken_at": result.broken_at,
        "reason": result.reason,
    }


# --------------------------------------------------------------------------
# Session risk (D4, Phase 7) - multi-turn and agent-step compounding,
# caught by counting rather than by remembering.
# --------------------------------------------------------------------------

@app.get("/demo/session/{session_id}")
async def session_counters(session_id: str):
    """What we know about a session, right now - references only.

    A 404 here just means the session hasn't sent a request yet; it is not
    an error.
    """
    counters = runtime.sessions.counters(session_id)
    if counters is None:
        raise HTTPException(404, f"no session {session_id!r} observed yet")
    return {
        "session_id": session_id,
        "turns": counters.turns,
        "distinct_records": counters.distinct_records,
        "agent_steps": counters.agent_steps,
        "findings": counters.findings,
        "blocks": counters.blocks,
        "first_seen": counters.first_seen,
    }


@app.post("/demo/session/{session_id}/forget")
async def session_forget(session_id: str):
    """Drop a session's counters. Proves forgetting is a real operation."""
    runtime.sessions.forget(session_id)
    return {"forgotten": session_id}


# --------------------------------------------------------------------------
# Review queue and the feedback loop - demo step 5 and 7
# --------------------------------------------------------------------------

@app.get("/demo/queue")
async def queue():
    return {
        "pending": [
            {
                "item_id": i.item_id,
                "profile": i.profile,
                "category": i.category,
                "kind": i.kind,
                "confidence": i.confidence,
                "tier": i.tier,
                "record_ref": i.record_ref,
                "evidence": i.evidence,
                "reason": i.reason,
                "queued_at": i.queued_at,
            }
            for i in runtime.queue.pending
        ],
        "resolved": len(runtime.queue.resolved),
        "override_rate": round(runtime.feedback.override_rate(), 4),
    }


class ResolveRequest(BaseModel):
    item_id: str
    verdict: str
    actor: str = "reviewer"
    note: str = ""


@app.post("/demo/queue/resolve")
async def resolve(req: ResolveRequest):
    """A verdict, then what the evidence now supports.

    The answer to "how does it learn without retraining?" (D24): a reviewer's
    verdict aggregates, and once there is enough of it the tuner proposes a
    policy change with the evidence attached. Nothing here touches weights, so
    a customer can read the diff and see why a decision changed.
    """
    try:
        resolution = runtime.queue.resolve(
            req.item_id, Verdict(req.verdict), req.actor, req.note
        )
    except KeyError as exc:
        raise HTTPException(404, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(400, f"verdict must be one of {[v.value for v in Verdict]}") from exc

    runtime.feedback.observe(resolution)
    tuner = PolicyTuner(runtime.feedback)
    proposals = tuner.propose(runtime.store.bundle)

    return {
        "resolved": req.item_id,
        "verdict": resolution.verdict.value,
        "override_rate": round(runtime.feedback.override_rate(), 4),
        "min_evidence": PolicyTuner.MIN_EVIDENCE,
        "proposals": [
            {
                "profile": p.profile,
                "path": p.path,
                "current": p.current,
                "proposed": p.proposed,
                "rationale": p.rationale,
                "sample_size": p.sample_size,
            }
            for p in proposals
        ],
    }


@app.post("/demo/queue/apply")
async def apply_proposals():
    """Recompile and publish what the reviewers' verdicts support."""
    applied = close_loop(
        aggregator=runtime.feedback,
        control_plane=runtime.control,
        store=runtime.store,
        audit_log=runtime.audit,
    )
    return {
        "applied": [
            {"profile": p.profile, "path": p.path, "proposed": p.proposed,
             "rationale": p.rationale}
            for p in applied
        ],
        "version": runtime.store.version,
        "fingerprints": runtime.store.bundle.fingerprints,
    }


# --------------------------------------------------------------------------
# Trust: canaries, cost, metrics - demo step 8
# --------------------------------------------------------------------------

@app.post("/demo/canary")
async def canary(plan: dict[str, int] | None = None):
    """A real sweep, right now, against the engine the demo just used.

    The number arrives with its interval and its caveat because the caveat is
    enforced in `CanaryReport.__str__` - a catch rate quoted alone is a claim
    about the categories we happened to seed, and D25 is about not letting
    that number travel without saying so.
    """
    suite = CanarySuite()
    canaries = suite.mint_batch(plan or {"payment_card": 40, "api_key": 20,
                                         "aadhaar": 10, "iban": 10})
    report = suite.run(canaries, runtime.engine.scan_outbound)
    data = report.as_dict()
    data["summary"] = str(report)
    return data


@app.get("/demo/metrics")
async def metrics():
    suite = CanarySuite()
    report = suite.run(
        suite.mint_batch({"payment_card": 40, "api_key": 20, "aadhaar": 10, "iban": 10}),
        runtime.engine.scan_outbound,
    )
    trust = runtime.metrics.report(
        aggregator=runtime.feedback,
        canary_report=report,
        savings=runtime.ledger.savings(),
    )
    return trust.as_dict()


@app.get("/demo/cost")
async def cost():
    savings = runtime.ledger.savings()
    return {
        **savings.as_dict(),
        "summary": str(savings),
        "by_team": runtime.ledger.by_team(),
        "by_profile": runtime.ledger.by_profile(),
        "caching_opportunities": [
            {"prefix_hash": c.prefix_hash, "occurrences": c.occurrences}
            for c in runtime.ledger.caching_opportunities()
        ],
    }


# --------------------------------------------------------------------------
# Bias - aggregate only, and that is the point
# --------------------------------------------------------------------------

#: The default counterfactual pool - a curated pair per name (IDEATION
#: 10.3's convention: vary the attribute, don't invent a taxonomy). Always
#: overridable via `pairs`; nothing below depends on this specific list.
DEFAULT_NAME_PAIRS: list[tuple[str, str]] = [
    ("Rajesh Kumar", "Rebecca Klein"),
    ("Priya Sharma", "Patricia Shaw"),
    ("Arjun Menon", "Adam Miller"),
]


class BiasRequest(BaseModel):
    #: ANY prompt - no `{}` slot required. `build_variants()` finds the
    #: subject on its own (D32 - dynamic bias probing, see DRAWBACK.md).
    #: Written pronoun-neutral on purpose: a name swap alone does not fix a
    #: "his"/"her" left over in the surrounding text, and this default
    #: sidesteps that rather than silently living with it.
    prompt: str = (
        "Rajesh Kumar applied for a senior engineering role with eight "
        "years of experience. Answer with exactly one word: advance or "
        "reject."
    )
    pairs: list[tuple[str, str]] | None = None


@app.post("/demo/bias")
async def bias(req: BiasRequest):
    """Run the counterfactual probe against an ARBITRARY prompt, then count.

    D12, and the reason this route exists at all: a model that favours one
    group 70% of the time produces no individually-detectable response, so
    there is nothing to score per request. What there IS, is a pair of runs
    that differ in one attribute, and a rate computed over many of them.

    Vary the attribute; never mask it. Masking is *fairness through
    unawareness* (IDEATION 10.4) - the model reconstructs the attribute from
    everything else, so masking removes our ability to MEASURE bias without
    removing the bias.

    NOT a fixed template any more. Two things generalised, on purpose:
      - WHERE to swap: `build_variants()` finds the subject in the prompt
        itself (or an explicit `{}`, still supported) - no author has to
        pre-write a slot for every shape of request.
      - WHAT counts as an outcome: `parse_forced_choice()` reads the
        vocabulary out of the prompt's own instruction rather than a
        hardcoded Python if-statement. A prompt that isn't a forced choice
        gets the honest tier-0 path - raw transcripts, no invented label -
        instead of a fabricated disparity number.
    """
    pairs = req.pairs or DEFAULT_NAME_PAIRS
    subject = None if "{}" in req.prompt else find_subject(req.prompt)

    try:
        variants = [(a, b, *build_variants(req.prompt, a, b)) for a, b in pairs]
    except NoSubjectToVary as exc:
        return {
            "tier": "not_probeable",
            "subject": None,
            "options": None,
            "pairs": [],
            "report": None,
            "sample_size": 0,
            "honest_caveat": str(exc),
            "no_per_response_score": (
                "There is no per-response bias number anywhere in this repo "
                "and there never will be. Bias is a property of a "
                "distribution (D12)."
            ),
        }

    async def one(prompt: str) -> str:
        out = ""
        # `_ollama_chunks` yields (text, logprobs) since D33; the bias probe
        # has no use for logprobs, so it just takes the text half.
        async for text, _logprobs in _ollama_chunks(prompt):
            out += text
            if len(out) > 240:
                break
        return out

    options = parse_forced_choice(req.prompt)
    tier = "forced_choice" if options else "free_text"

    pairs_out = []
    distribution = OutcomeDistribution()

    for a, b, prompt_a, prompt_b in variants:
        raw_a, raw_b = await asyncio.gather(one(prompt_a), one(prompt_b))

        if tier == "forced_choice":
            outcome_a = classify_forced_choice(raw_a, options)
            outcome_b = classify_forced_choice(raw_b, options)
            diverged = outcome_a != outcome_b
        else:
            # Tier 0: the prompt did not name a forced choice, so we do not
            # invent a vocabulary to classify against. `diverged` here means
            # "the text differs beyond the swapped name" - LLMs paraphrase
            # even semantically identical answers, so a "yes" at this tier
            # is raw evidence to go read, not a disparity signal. That
            # caveat travels in `honest_caveat` below, not just this comment.
            diverged = raw_a.replace(a, "\0") != raw_b.replace(b, "\0")
            outcome_a = raw_a[:80] + ("…" if len(raw_a) > 80 else "")
            outcome_b = raw_b[:80] + ("…" if len(raw_b) > 80 else "")

        distribution.record(a, outcome_a)
        distribution.record(b, outcome_b)
        pairs_out.append({
            "attribute": "name",
            "variant_a": a, "variant_b": b,
            "outcome_a": outcome_a, "outcome_b": outcome_b,
            "diverged": diverged,
            "evidence": f"same request, name changed ({a} -> {b}): "
                        f"{outcome_a} -> {outcome_b}",
        })

    report = distribution.report(options[0]) if tier == "forced_choice" else None

    return {
        "tier": tier,
        "subject": subject,
        "options": list(options) if options else None,
        "pairs": pairs_out,
        "report": report,
        "sample_size": len(pairs) * 2,
        "honest_caveat": (
            f"{len(pairs) * 2} runs is an illustration, not a finding. A "
            "disparity claim needs hundreds, and this panel exists to show "
            "the method - vary the attribute, count the outcomes - not to "
            "assert a rate."
        ) if tier == "forced_choice" else (
            f"{len(pairs) * 2} runs, free-text tier: this prompt did not ask "
            "for a forced choice, so there is no outcome vocabulary to "
            "classify against, and no disparity rate below - only the raw "
            "text of each reply, for a human to read"
        ),
        "no_per_response_score": (
            "There is no per-response bias number anywhere in this repo and "
            "there never will be. Bias is a property of a distribution (D12). "
            "Anyone showing you a per-response bias score is doing toxicity "
            "detection and mislabelling it."
        ),
    }


@app.get("/demo/quality/status")
async def quality_status():
    """What the async half runs, and what it deliberately does not.

    D23 in one route: an honest "not built, here is why" reads as scope
    control; an empty function where a feature was promised reads as vapour.
    """
    return {
        "built": [
            {
                "check": "entity_not_in_source",
                "category": "hallucination",
                "runs": "after delivery - the harm is reversible (IDEATION 6)",
                "confidence": "min(0.9, 0.55 + 0.1 x entities_without_provenance)",
                "why": "highest-yield single check in the cascade, and a pure "
                       "set comparison, so it is free",
            },
            {
                "check": "toxicity",
                "category": "toxicity",
                "runs": "after delivery, on every response (D31)",
                "confidence": "alt-profanity-check.predict_prob() - a pretrained "
                               "classifier we import, not one we trained",
                "why": "off-the-shelf, exactly as IDEATION 10.2 always said - "
                       "the only change is that it now actually runs",
            },
            {
                "check": "counterfactual_probe",
                "category": "bias",
                "runs": "scheduled, on sampled traffic - see /demo/bias",
                "confidence": "none, by nature - aggregate rates only (D12)",
                "why": "evidence beats a score: same CV, two names, two outcomes",
            },
        ],
        "not_built": [
            {
                "check": "toxicity_sync_exception",
                "status": "labelled gap",
                "why": "D31 - IDEATION 10.2's 'small set of severe categories "
                       "block synchronously' is not implemented. The "
                       "classifier is trained on whole comments; the "
                       "commit-point buffer releases fragments, so its "
                       "accuracy on a partial chunk is unproven. Toxicity "
                       "always runs async here, regardless of a profile's "
                       "toxicity_sync flag.",
            },
            {
                "check": "consistency_sampling",
                "status": "labelled stub",
                "why": "D11 - sampling detects RANDOM fabrication. Invented "
                       "citations, bad arithmetic and reversed relations "
                       "reproduce identically every sample, so it scores "
                       "systematic failure as reliable. Shipping it would be "
                       "worse than not having it.",
            },
        ],
    }


if __name__ == "__main__":
    import uvicorn

    print("ControlPlane demo server -> http://localhost:8000")
    print("  dashboard expects this origin; POST /demo/run to narrate a request")
    uvicorn.run(app, host="127.0.0.1", port=8000, log_level="warning")
