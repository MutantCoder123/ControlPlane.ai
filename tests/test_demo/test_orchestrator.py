"""The demo pipeline, driven by a fake model.

WHY THESE EXIST AT ALL
----------------------
The demo surface is the thing a judge actually watches, and until now it was
the only part of the repo with no tests. That is backwards: a bug in the
engine shows up as a failing test, a bug here shows up on stage.

Every test below drives the real orchestrator with a fake token stream, so
none of them needs a running model - the same reason TRACK-B.md puts the
provider behind a small interface.
"""

from __future__ import annotations

import asyncio

import pytest

from controlplane.demo.orchestrator import DemoRuntime


@pytest.fixture()
def runtime():
    return DemoRuntime()


def drive(runtime, prompt, chunks, **kw) -> list[dict]:
    """Run the pipeline with a scripted model reply. Returns every event."""

    async def fake(_prompt):
        for chunk in chunks:
            yield chunk

    import controlplane.demo.orchestrator as orch

    real, orch._ollama_chunks = orch._ollama_chunks, fake
    try:
        async def collect():
            return [e async for e in runtime.run(prompt, **kw)]

        return asyncio.run(collect())
    finally:
        orch._ollama_chunks = real


def stages(events, stage):
    return [e for e in events if e["stage"] == stage]


def one(events, stage):
    found = stages(events, stage)
    assert found, f"no {stage} event in {[e['stage'] for e in events]}"
    return found[0]


# --------------------------------------------------------------------------
# The claim the whole product rests on
# --------------------------------------------------------------------------

def test_no_real_value_is_ever_dispatched(runtime):
    """The one assertion that, if it fails, the pitch is untrue.

    Not "a placeholder appeared" - that a placeholder appeared says nothing
    about whether the original also survived somewhere else in the string.
    This asserts the absence of every mapped value.
    """
    events = drive(
        runtime,
        "Email Priya Sharma at priya.sharma@example.com about 45230.",
        ["Done."],
    )
    scan, dispatch = one(events, "scan.inbound"), one(events, "dispatch")

    assert scan["mapping"], "nothing was substituted, so this proves nothing"
    for value in scan["mapping"].values():
        assert value not in dispatch["text"]
    assert dispatch["leak_check"]["ok"]
    assert dispatch["leak_check"]["leaked"] == []


def test_the_operand_is_dispatched_untouched(runtime):
    """D16. Break the linkage, preserve the arithmetic.

    If the balance were substituted too, the model could not compute with it
    and the answer would be useless - which is the failure mode that makes
    redaction-based products unusable.
    """
    events = drive(runtime, "Priya Sharma has a balance of 45230.", ["ok"])
    assert "45230" in one(events, "dispatch")["text"]


def test_a_credential_is_refused_before_anything_is_dispatched(runtime):
    """The ordering in IDEATION section 8, as a test rather than a diagram."""
    events = drive(
        runtime,
        "Use key sk-abcdefghij0123456789ABCDEFGHIJ to call it.",
        ["this should never be generated"],
    )

    assert stages(events, "dispatch") == []
    assert stages(events, "stream.raw") == []
    block = one(events, "block")
    assert block["where"] == "inbound"
    assert block["cost_usd"] == 0.0
    assert one(events, "done")["outcome"] == "blocked"


def test_a_substituted_record_is_allowed_through(runtime):
    """The regression that would have blocked every useful prompt.

    A known-value name matches at confidence 1.0, over `block_at`. Without
    mitigation the product refuses the exact input it exists to handle.
    """
    events = drive(runtime, "Refund Priya Sharma 45230.", ["Refunded."])
    assert one(events, "decision")["tier"] == "allow"
    assert stages(events, "block") == []


# --------------------------------------------------------------------------
# The buffer is the real one
# --------------------------------------------------------------------------

def test_releases_carry_the_commit_rule_that_fired(runtime):
    """P4 is doing the buffering, not a substring check in the demo server.

    `trigger` can only be set by `CommitPointBuffer._commit`, so its presence
    is evidence about which code ran.
    """
    events = drive(
        runtime,
        "Note about Priya Sharma.",
        ["Hello ", "there. ", "This is a second sentence. ", "And a third."],
    )
    releases = stages(events, "buffer.release")

    assert releases
    assert all(r["trigger"] in {"boundary", "tokens", "timeout", "flush"} for r in releases)
    assert any(r["trigger"] == "boundary" for r in releases), (
        "a sentence boundary should be the commit point in interactive mode"
    )


def test_a_placeholder_split_across_chunks_still_restores(runtime):
    """D15 at the seam.

    The model's tokeniser does not respect our placeholder format, so
    `[[CUST_A]]` routinely arrives in pieces. If the buffer released on chunk
    boundaries this would restore as literal artefacts on stage.
    """
    events = drive(
        runtime,
        "Write to Priya Sharma.",
        ["Dear [[C", "UST", "_A]], your refund is ready. Thank you."],
    )
    done = one(events, "answer.done")

    assert "Priya Sharma" in done["answer"]
    assert done["unrestored"] == []
    assert "[[" not in done["answer"]


def test_the_overlap_cut_itself_does_not_bisect_a_placeholder(runtime):
    """The bug the earlier test could not catch, found by watching the demo.

    `test_a_placeholder_split_across_chunks_still_restores` reassembles the
    placeholder into ONE pending buffer before any commit fires, so the
    whole token sits comfortably inside the 50-char hold. It says nothing
    about the OTHER way a placeholder can split: the fixed-size hold itself
    landing mid-token, when there happen to be roughly 41-49 characters of
    real trailing text after it in the same commit window. That gap is
    exactly what beat 1 of the demo hit on a live model.

    370 characters total, arranged so `window_len - overlap_chars(50)` lands
    inside the ten-character placeholder: 315 filler characters first
    (driving the commit via token count), then the placeholder, then exactly
    45 characters after it. `315 + 10 + 45 - 50 = 320` - five characters into
    the placeholder, not before its start or past its end. What matters here
    is that this reliably reproduces the bisection at the profile's REAL
    overlap_chars, not a shrunk test value.
    """
    events = drive(
        runtime,
        "Write to Priya Sharma.",
        ["filler " * 45 + "[[CUST_A]]" + "z" * 45],
    )
    done = one(events, "answer.done")

    assert "Priya Sharma" in done["answer"]
    assert done["unrestored"] == []
    assert "[[" not in done["answer"]
    for release in stages(events, "buffer.release"):
        opens, closes = release["text"].count("["), release["text"].count("]")
        assert opens == closes, f"a bracket escaped without its pair: {release['text']!r}"


def test_the_unrestored_alarm_checks_what_was_actually_delivered(runtime, monkeypatch):
    """The alarm has to watch the STREAM, not re-grade a clean copy of itself.

    Before this test existed, `answer.done`'s `unrestored` was computed by
    re-running `restore()` on the full raw model output - which is always
    whole, because it was never bisected by a commit boundary. That always
    passed, even while the STREAMED `answer` (the thing actually rendered)
    contained a broken placeholder. An alarm that cannot see the failure it
    exists to catch is worse than no alarm: it reports "0 unrestored" on the
    exact request that just failed.

    This disables the buffer's seam-guard (simulating a future regression in
    it) and asserts the alarm still fires - proving the alarm is now wired to
    `answer`, independently of whether the guard above continues to work.
    """
    import re as _re

    import controlplane.stream.buffer as buffer_module

    monkeypatch.setattr(buffer_module, "_DANGLING_OPEN_RE", _re.compile(r"(?!)"))

    events = drive(
        runtime,
        "Write to Priya Sharma.",
        ["filler " * 45 + "[[CUST_A]]" + "z" * 45],
    )
    done = one(events, "answer.done")

    assert "[[" in done["answer"], "the guard is disabled - this run SHOULD bisect"
    assert done["unrestored"], "the alarm must fire when the delivered text is broken"


def test_an_outbound_credential_stops_the_stream(runtime):
    """Not released, then retracted - never released.

    Once a token reaches the browser it is in the DOM and in the stream, so a
    kill switch after render is theatre. The buffer holds text until it has
    been scanned as one piece with what follows.
    """
    events = drive(
        runtime,
        "Summarise the runbook.",
        ["Use the key ", "sk-abcdefghij0123456789ABCDEFGHIJ", " to authenticate."],
    )
    block = one(events, "block")

    assert block["where"] == "outbound"
    released = "".join(r["text"] for r in stages(events, "buffer.release"))
    assert "sk-abcdefghij0123456789ABCDEFGHIJ" not in released


# --------------------------------------------------------------------------
# The reversible half really is on the other side of delivery
# --------------------------------------------------------------------------

def test_quality_findings_arrive_after_the_answer(runtime):
    """IDEATION section 6, as an ordering assertion.

    If a quality event could precede `answer.done`, the reversibility split
    would be a diagram rather than a property of the code.
    """
    events = drive(
        runtime,
        "Notes: Priya Sharma, balance 45230.",
        ["Contact Ramesh Krishnan about 99999 rupees today."],
    )
    done = one(events, "answer.done")
    findings = stages(events, "quality.finding")

    assert findings, "an invented name and figure should have been flagged"
    assert all(f["seq"] > done["seq"] for f in findings)
    assert all(f["t_ms"] >= done["t_ms"] for f in findings)
    assert all(f["reversible"] for f in findings)


def test_the_hallucination_confidence_is_the_documented_formula(runtime):
    """A number on screen has to be reproducible from what is shown beside it."""
    events = drive(
        runtime,
        "Notes: Priya Sharma.",
        ["Contact Ramesh Krishnan on 4400 about 99999 rupees."],
    )
    finding = one(events, "quality.finding")
    # detail reads "1 of N entities absent..." (D33: one finding per entity,
    # sharing the same density-derived base) - N is the third word.
    invented = finding["detail"].split()[2]

    assert finding["confidence"] == pytest.approx(min(0.9, 0.55 + 0.1 * int(invented)))
    assert "0.55 + 0.1" in finding["confidence_formula"]


# --------------------------------------------------------------------------
# D33 - real per-token confidence, span highlighting, two more claim shapes
# --------------------------------------------------------------------------

def test_a_flagged_entity_carries_its_answer_span(runtime):
    """The span is what lets the dashboard highlight the exact substring,
    not just list it below the response."""
    answer = "Contact Ramesh Krishnan about 99999 rupees today."
    events = drive(runtime, "Notes: Priya Sharma, balance 45230.", [answer])
    findings = stages(events, "quality.finding")
    halluc = [f for f in findings if f["check"] == "entity_not_in_source"]

    assert halluc
    for f in halluc:
        start, end = f["span"]
        assert answer[start:end] in f["evidence"]


def test_toxicity_findings_carry_no_span(runtime):
    """Toxicity describes the whole reply, not one substring - span is None,
    not a made-up range."""
    events = drive(
        runtime, "How is my complaint being handled?",
        ["your service is a joke and your staff are incompetent morons."],
    )
    toxic = [f for f in stages(events, "quality.finding") if f["check"] == "toxicity"]
    assert toxic
    assert toxic[0]["span"] is None


def test_a_real_logprob_dip_sharpens_confidence_through_the_real_pipeline(runtime):
    """Not a unit test of `_logprob_dip` in isolation - this drives the
    ACTUAL orchestrator with a scripted (text, logprobs) chunk, the same
    shape the real Ollama client yields, and checks the finding that comes
    out the other end names the real signal."""
    answer = "Contact Ramesh Krishnan about 99999 rupees today."
    # One chunk, all tokens confident except "99999" - the classic
    # fluent-except-for-the-fabricated-figure fingerprint (IDEATION 11.5).
    tokens = [
        ("Contact Ramesh Krishnan about ", -0.05),
        ("99999", -3.0),
        (" rupees today.", -0.05),
    ]
    chunk_text = "".join(t for t, _ in tokens)
    logprobs = [{"token": t, "logprob": lp} for t, lp in tokens]

    events = drive(
        runtime, "Notes: Priya Sharma, balance 45230.",
        [(chunk_text, logprobs)],
    )
    findings = stages(events, "quality.finding")
    figure = next(f for f in findings if "99999" in f["evidence"])
    name = next(f for f in findings if "Ramesh Krishnan" in f["evidence"])

    assert "REAL per-token probability" in figure["confidence_formula"]
    assert figure["confidence"] > name["confidence"]


def test_overclaiming_language_is_flagged_with_no_entity_at_all(runtime):
    events = drive(
        runtime, "Will this plan work for me?",
        ["This plan always works and is guaranteed to help."],
    )
    overclaims = [f for f in stages(events, "quality.finding") if f["category"] == "overclaim"]
    assert overclaims
    assert all(f["reversible"] for f in overclaims)


def test_an_invented_reason_is_flagged_as_hallucination(runtime):
    events = drive(
        runtime, "Why was my request delayed?",
        ["Your request was delayed because of a rare synchronisation fault."],
    )
    causal = [f for f in stages(events, "quality.finding")
              if f["check"] == "unsupported_causal_claim"]
    assert causal
    assert causal[0]["category"] == "hallucination"


def test_a_high_risk_route_sends_a_quality_finding_to_a_human(runtime):
    """Demo step 5 has to have something in the queue.

    `decision-support` reviews every response because the legal exposure
    justifies the cost, not because confidence was low.
    """
    events = drive(
        runtime,
        "Notes: Priya Sharma.",
        ["Contact Ramesh Krishnan about 99999 rupees."],
        profile_name="decision-support",
    )
    queued = stages(events, "queue.enqueue")

    assert queued
    assert queued[0]["reason"] == "profile reviews every response"
    assert runtime.queue.pending


# --------------------------------------------------------------------------
# Toxicity (D31) - runs on every reply, not just ones with entities
# --------------------------------------------------------------------------

# Insult-laden but with no number, date or capitalised proper noun - the
# exact shape that used to be invisible to the whole quality pass (see the
# comment in `_quality_pass`), because `has_checkable_claims` gated toxicity
# along with entity_not_in_source before this was caught and fixed.
_TOXIC_REPLY = "your service is a joke and your staff are incompetent morons."


def test_a_toxic_reply_with_no_entities_is_still_flagged(runtime):
    events = drive(runtime, "How is my complaint being handled?", [_TOXIC_REPLY])
    findings = stages(events, "quality.finding")

    assert any(f["check"] == "toxicity" for f in findings), (
        "toxicity must fire even when entity_not_in_source has nothing to check"
    )


def test_toxicity_never_blocks_a_delivered_answer(runtime):
    """Reversible harm is annotated after the reader already has the answer -
    the response must reach `answer.done` before the toxicity finding does."""
    events = drive(runtime, "How is my complaint being handled?", [_TOXIC_REPLY])
    done = one(events, "answer.done")
    finding = one(events, "quality.finding")

    assert done["answer"] == _TOXIC_REPLY
    assert finding["seq"] > done["seq"]
    assert finding["reversible"] is True


def test_a_clean_reply_reports_toxicity_as_run_but_not_flagged(runtime):
    """`ran` proves the check executed; an empty finding list proves it found
    nothing - two different claims, and only the code can make both at once."""
    events = drive(runtime, "How is my complaint being handled?", ["We are looking into it."])
    done_quality = one(events, "quality.done")

    assert "toxicity" in done_quality["ran"]
    assert not any(f["check"] == "toxicity" for f in stages(events, "quality.finding"))


def test_a_reply_with_no_entities_and_no_toxicity_still_runs_toxicity(runtime):
    """The bug this replaces: an answer with nothing for entity_not_in_source
    to check used to skip the ENTIRE pass, silently, including toxicity."""
    events = drive(runtime, "How is my complaint being handled?", ["We are looking into it."])
    done_quality = one(events, "quality.done")

    # D33 added two more checks with the same "no entity required" property
    # as toxicity - they run here too, unconditionally.
    assert done_quality["ran"] == ["overclaim", "unsupported_causal_claim", "toxicity"]
    assert "entity_not_in_source" not in done_quality["ran"]
    assert done_quality["skipped"]


# --------------------------------------------------------------------------
# The record keeping
# --------------------------------------------------------------------------

def test_the_audit_entry_holds_references_and_no_values(runtime):
    events = drive(runtime, "Refund Priya Sharma 45230.", ["Done."])
    entry = one(events, "audit.append")["entry"]

    assert "Priya" not in repr(entry)
    assert "45230" not in repr(entry)
    assert entry["payload"]["findings"][0]["record_ref"] == "customer:44219"
    assert runtime.audit.verify()


def test_a_request_id_that_is_all_digits_does_not_crash_the_audit_log(runtime, monkeypatch):
    """A flaky failure this suite hit by chance, made deterministic and fixed.

    `uuid.uuid4().hex[:12]` is drawn from 0-9a-f, so roughly 1 in 300 requests
    would land on 12 characters that are ALL digits - which the audit log's
    own guard refuses to write, reading it as a possible card or account
    number (`\\b\\d{12,19}\\b`). That crashed a live request non-deterministically,
    including during test runs, which is how it was found. Forcing the
    worst case here makes sure the id's prefix keeps defusing it.
    """
    import uuid as uuid_module

    class AllDigits:
        hex = "123456789012"

    monkeypatch.setattr(uuid_module, "uuid4", lambda: AllDigits())

    events = drive(runtime, "Refund Priya Sharma 45230.", ["Done."])
    assert stages(events, "error") == []
    assert one(events, "audit.append")["entry"]["payload"]["request_id"].startswith("req_")


def test_the_audit_event_does_not_shadow_the_stream_sequence(runtime):
    """An entry carries its own `seq`; splatting it renumbered the event.

    The tape is a timeline, and an event that reports seq 0 halfway through
    renders as arriving out of order.
    """
    events = drive(runtime, "Refund Priya Sharma 45230.", ["Done."])
    assert [e["seq"] for e in events] == sorted(e["seq"] for e in events)
    assert all(e["seq"] > 0 for e in events)


def test_a_blocked_request_is_still_written_down(runtime):
    """Refusing is a governance event, not a non-event."""
    events = drive(runtime, "Key sk-abcdefghij0123456789ABCDEFGHIJ here.", ["x"])
    entry = one(events, "audit.append")["entry"]

    assert entry["payload"]["blocked"] is True
    assert entry["payload"]["findings"][0]["category"] == "api_key"


def test_every_event_declares_which_side_of_the_line_it_belongs_to(runtime):
    """The dashboard renders `inside` left and `outside` right.

    An unlabelled event is one a future edit could render on the wrong side,
    which on this page means printing a real value in the provider's column.
    """
    events = drive(runtime, "Refund Priya Sharma 45230.", ["Done."])
    assert all(e["side"] in {"inside", "outside", "meta"} for e in events)
    assert one(events, "dispatch")["side"] == "outside"


# --------------------------------------------------------------------------
# Session risk (D4) - multi-turn and agent-step compounding, caught by
# counting rather than by remembering. The Round 2 brief names this directly.
# --------------------------------------------------------------------------

def test_no_session_id_means_no_session_tracking(runtime):
    """An anonymous request has no session to accumulate against.

    We never mint our own id - see the module docstring on why - so omitting
    one has to be a real, silent no-op rather than a fallback identity that
    would let unrelated anonymous callers pool into one bucket.
    """
    events = drive(runtime, "Refund Priya Sharma 45230.", ["Done."])
    assert stages(events, "session.risk") == []
    assert len(runtime.sessions) == 0


def test_a_quiet_session_reports_no_risk(runtime):
    events = drive(runtime, "Refund Priya Sharma 45230.", ["Done."], session_id="sess-1")
    risk = one(events, "session.risk")
    assert risk["turns"] == 1
    assert risk["distinct_records"] == 1
    assert not risk["over_budget"]
    assert risk["reasons"] == []


def test_the_budget_trips_on_the_fourth_distinct_customer(runtime):
    """internal-knowledge caps at 3 distinct records per session (Phase 7) -
    small on purpose, so this trips inside a four-turn demo beat.

    No single one of these four prompts is individually alarming. That is
    the point: the compounding is only visible in the aggregate.
    """
    names = ["Priya Sharma", "Rajesh Kumar", "Kavya Reddy", "Anita Desai"]
    last = None
    for name in names:
        events = drive(
            runtime, f"Summarise the account note for {name}.", ["Noted."],
            session_id="sess-multi",
        )
        last = one(events, "session.risk")

    assert last["turns"] == 4
    assert last["distinct_records"] == 4
    assert last["over_budget"]
    assert "cumulative disclosure" in last["reasons"][0]
    assert "limit 3" in last["reasons"][0]


def test_tripping_the_budget_does_not_block_the_request(runtime):
    """A cumulative verdict is evidence about a pattern, not proof about this
    request. Severing turn four of a legitimate investigation is exactly the
    over-flagging failure the brief warns about - the session is flagged,
    the request still runs.
    """
    for name in ["Priya Sharma", "Rajesh Kumar", "Kavya Reddy", "Anita Desai"]:
        events = drive(
            runtime, f"Summarise the account note for {name}.", ["Noted."],
            session_id="sess-still-runs",
        )
    assert stages(events, "block") == []
    assert one(events, "answer.done")


def test_two_sessions_do_not_contaminate_each_other(runtime):
    drive(runtime, "Refund Priya Sharma.", ["Done."], session_id="sess-a")
    events = drive(runtime, "Refund Rajesh Kumar.", ["Done."], session_id="sess-b")
    risk = one(events, "session.risk")
    assert risk["turns"] == 1
    assert risk["distinct_records"] == 1


def test_the_session_event_carries_no_prompt_and_no_value(runtime):
    """Same reference-only discipline as the audit entry (D4, IDEATION 3)."""
    events = drive(runtime, "Refund Priya Sharma 45230.", ["Done."], session_id="sess-clean")
    risk = one(events, "session.risk")
    blob = repr(risk)
    assert "Priya" not in blob and "Sharma" not in blob and "45230" not in blob


def test_agent_steps_accumulate_toward_the_step_budget(runtime):
    events = drive(
        runtime, "Refund Priya Sharma.", ["Done."],
        session_id="sess-agent", agent_steps=41,
    )
    risk = one(events, "session.risk")
    assert risk["agent_steps"] == 41
    assert risk["over_budget"]
    assert "agent sprawl" in risk["reasons"][0]
    assert one(events, "scan.inbound")["side"] == "inside"
