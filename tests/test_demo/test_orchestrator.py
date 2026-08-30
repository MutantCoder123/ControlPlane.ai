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
    invented = finding["detail"].split()[0]

    assert finding["confidence"] == pytest.approx(min(0.9, 0.55 + 0.1 * int(invented)))
    assert "0.55 + 0.1" in finding["confidence_formula"]


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
# The record keeping
# --------------------------------------------------------------------------

def test_the_audit_entry_holds_references_and_no_values(runtime):
    events = drive(runtime, "Refund Priya Sharma 45230.", ["Done."])
    entry = one(events, "audit.append")["entry"]

    assert "Priya" not in repr(entry)
    assert "45230" not in repr(entry)
    assert entry["payload"]["findings"][0]["record_ref"] == "customer:44219"
    assert runtime.audit.verify()


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
    assert one(events, "scan.inbound")["side"] == "inside"
