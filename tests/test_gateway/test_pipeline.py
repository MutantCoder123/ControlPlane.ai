"""Tests for Gateway Pipeline (P1 / B6).

Verifies IDEATION §8: credential refusal BEFORE dispatch with cost_usd 0.0 (fake provider never called).
Verifies end-to-end substitution -> dispatch -> restoration round trip.
"""

from __future__ import annotations

import json
import os
import pytest
from controlplane.engine.substitute import SubstitutionEngine
from controlplane.gateway.context import create_request_context
from controlplane.gateway.pipeline import GatewayPipeline
from controlplane.gateway.upstream import FakeUpstreamClient

FIXTURES_PATH = os.path.join(
    os.path.dirname(__file__), "..", "test_engine", "fixtures", "records.jsonl"
)


@pytest.mark.anyio
async def test_credential_refused_before_dispatch():
    """IDEATION §8: Refusal must happen BEFORE dispatch, costing $0.00.

    Asserts fake provider's call count is ZERO.
    """
    engine = SubstitutionEngine(FIXTURES_PATH)
    fake_upstream = FakeUpstreamClient()
    pipeline = GatewayPipeline(engine=engine, upstream=fake_upstream)

    ctx = create_request_context(headers={"X-ControlPlane-Profile": "customer-support"})
    messages = [
        {"role": "user", "content": "Here is API key: sk-proj-1234567890abcdef1234567890abcdef for lookup."}
    ]

    res = await pipeline.execute_chat(messages=messages, context=ctx, model="gpt-4o", stream=False)

    # 1. Fake provider was NEVER called!
    assert fake_upstream.call_count == 0

    # 2. Refusal response returned to client with cost_usd 0.0
    assert res["controlplane"]["blocked"] is True
    assert res["controlplane"]["cost_usd"] == 0.0
    assert "refused" in res["choices"][0]["message"]["content"].lower()


@pytest.mark.anyio
async def test_normal_request_dispatched_and_restored():
    engine = SubstitutionEngine(FIXTURES_PATH)
    
    # Ask the engine what placeholder it will mint, rather than typing one.
    # CONTRACTS.md section 4: Track A owns the format and may change it; a
    # literal here is a live D15 bug even on the day it happens to match.
    prompt = "Please verify account for Priya Sharma."
    placeholder = engine.scan_inbound(prompt).findings[0].placeholder

    fake_upstream = FakeUpstreamClient(
        canned_response_text=f"Customer {placeholder} has an approved credit limit."
    )
    pipeline = GatewayPipeline(engine=engine, upstream=fake_upstream)

    ctx = create_request_context()
    messages = [{"role": "user", "content": prompt}]

    res = await pipeline.execute_chat(messages=messages, context=ctx, model="gpt-4o", stream=False)

    # 1. Fake provider was called once
    assert fake_upstream.call_count == 1

    # 2. Upstream provider received ONLY transformed text (placeholder)
    assert fake_upstream.last_messages is not None
    upstream_user_msg = fake_upstream.last_messages[0]["content"]
    assert "Priya Sharma" not in upstream_user_msg
    assert placeholder in upstream_user_msg

    # 3. Caller received restored response
    final_content = res["choices"][0]["message"]["content"]
    assert "Priya Sharma" in final_content
    assert placeholder not in final_content
    assert res["controlplane"]["blocked"] is False
    assert res["controlplane"]["restored_count"] == 1


@pytest.mark.anyio
async def test_list_content_is_scanned_not_waved_through():
    """A message whose content is a list of parts must still be scanned.

    The unmodified OpenAI SDK sends this shape routinely - it is what every
    multimodal and every tool-augmented client produces. Guarding on
    `isinstance(content, str)` meant those requests skipped the scanner
    entirely and the provider received the real record. An unscanned path is
    worse than a refused one, because nothing says it happened.
    """
    engine = SubstitutionEngine(FIXTURES_PATH)
    fake_upstream = FakeUpstreamClient()
    pipeline = GatewayPipeline(engine=engine, upstream=fake_upstream)

    messages = [
        {
            "role": "user",
            "content": [
                {"type": "text", "text": "Look up Priya Sharma please."},
                {"type": "text", "text": "Her email is priya.sharma@example.com."},
            ],
        }
    ]
    res = await pipeline.execute_chat(
        messages=messages, context=create_request_context(), model="gpt-4o", stream=False
    )

    sent = json.dumps(fake_upstream.last_messages)
    assert "Priya Sharma" not in sent
    assert "priya.sharma@example.com" not in sent
    assert res["controlplane"]["blocked"] is False


@pytest.mark.anyio
async def test_list_content_credential_is_still_refused_before_dispatch():
    """The pre-dispatch gate has to hold on this shape too (IDEATION section 8)."""
    engine = SubstitutionEngine(FIXTURES_PATH)
    fake_upstream = FakeUpstreamClient()
    pipeline = GatewayPipeline(engine=engine, upstream=fake_upstream)

    messages = [
        {
            "role": "user",
            "content": [
                {"type": "text", "text": "deploy with sk-proj-1234567890abcdef1234567890abcdef"}
            ],
        }
    ]
    res = await pipeline.execute_chat(
        messages=messages, context=create_request_context(), model="gpt-4o", stream=False
    )

    assert fake_upstream.call_count == 0
    assert res["controlplane"]["blocked"] is True
    assert res["controlplane"]["cost_usd"] == 0.0


@pytest.mark.anyio
async def test_streaming_restores_real_values_to_the_caller():
    """Streaming must restore too, or the reader watches placeholders appear.

    The old streaming path accumulated the response and threw it away, then
    yielded the upstream chunks untouched. Every test asserted only that SSE
    framing existed, so nobody noticed.
    """
    engine = SubstitutionEngine(FIXTURES_PATH)
    prompt = "Write one line about Priya Sharma."
    placeholder = engine.scan_inbound(prompt).findings[0].placeholder

    fake_upstream = FakeUpstreamClient(
        canned_response_text=f"Certainly. {placeholder} is a valued customer."
    )
    pipeline = GatewayPipeline(engine=engine, upstream=fake_upstream)

    gen = await pipeline.execute_chat(
        messages=[{"role": "user", "content": prompt}],
        context=create_request_context(),
        model="gpt-4o",
        stream=True,
    )
    streamed = ""
    async for chunk in gen:
        streamed += chunk["choices"][0].get("delta", {}).get("content", "") or ""

    assert "Priya Sharma" in streamed
    assert placeholder not in streamed


@pytest.mark.anyio
async def test_streaming_restores_a_placeholder_split_across_chunks():
    """The boundary case is the whole reason this needs a buffer.

    The fake emits word by word, so a placeholder lands in pieces. Restoring
    each chunk independently would never match it and the reader would see the
    token in fragments.
    """
    engine = SubstitutionEngine(FIXTURES_PATH)
    prompt = "Write one line about Priya Sharma."
    placeholder = engine.scan_inbound(prompt).findings[0].placeholder

    # Split the placeholder itself down the middle across two chunks.
    half = len(placeholder) // 2
    chunks = ["Our customer ", placeholder[:half], placeholder[half:], " is in good standing."]
    fake_upstream = FakeUpstreamClient(canned_chunks=chunks)
    pipeline = GatewayPipeline(engine=engine, upstream=fake_upstream)

    gen = await pipeline.execute_chat(
        messages=[{"role": "user", "content": prompt}],
        context=create_request_context(),
        model="gpt-4o",
        stream=True,
    )
    streamed = ""
    async for chunk in gen:
        streamed += chunk["choices"][0].get("delta", {}).get("content", "") or ""

    assert "Priya Sharma" in streamed
    assert placeholder not in streamed


@pytest.mark.anyio
async def test_two_customers_in_one_request_stay_distinct():
    """Different entities must get different placeholders across messages.

    Every scan used to start numbering at A, so two customers in one
    conversation both arrived upstream as the same token. Two harms, and the
    second is the worse one: the merged mapping restored the wrong name, and
    before that the model was told two different people were one person, so
    its answer was already wrong.

    Fixed on the engine side with RequestScope; this asserts the gateway
    actually threads one scope through the whole request.
    """
    engine = SubstitutionEngine(FIXTURES_PATH)
    fake_upstream = FakeUpstreamClient()
    pipeline = GatewayPipeline(engine=engine, upstream=fake_upstream)

    await pipeline.execute_chat(
        messages=[
            {"role": "user", "content": "First customer: Priya Sharma."},
            {"role": "user", "content": "Second customer: Rajesh Kumar."},
        ],
        context=create_request_context(),
        model="gpt-4o",
        stream=False,
    )

    sent = [m["content"] for m in fake_upstream.last_messages]
    first_ph = sent[0].split(": ")[1].rstrip(".")
    second_ph = sent[1].split(": ")[1].rstrip(".")
    assert first_ph != second_ph, sent


@pytest.mark.anyio
async def test_each_customer_restores_to_their_own_name():
    """The half that a judge would see: the right name comes back."""
    engine = SubstitutionEngine(FIXTURES_PATH)
    scope = engine.new_request_scope()
    a = engine.scan_inbound("First customer: Priya Sharma.", scope=scope)
    b = engine.scan_inbound("Second customer: Rajesh Kumar.", scope=scope)
    first_ph = a.findings[0].placeholder
    second_ph = b.findings[0].placeholder

    fake_upstream = FakeUpstreamClient(
        canned_response_text=f"I contacted {first_ph}, not {second_ph}."
    )
    pipeline = GatewayPipeline(engine=engine, upstream=fake_upstream)

    res = await pipeline.execute_chat(
        messages=[
            {"role": "user", "content": "First customer: Priya Sharma."},
            {"role": "user", "content": "Second customer: Rajesh Kumar."},
        ],
        context=create_request_context(),
        model="gpt-4o",
        stream=False,
    )

    answer = res["choices"][0]["message"]["content"]
    assert answer == "I contacted Priya Sharma, not Rajesh Kumar."
    assert res["controlplane"]["unrestored"] == []


@pytest.mark.anyio
async def test_the_same_customer_across_messages_stays_one_person():
    """The converse, and it is just as load-bearing.

    If Priya becomes a different placeholder in each message, the model can no
    longer tell it is one person and the answer degrades - which is what
    substitution is supposed to avoid (IDEATION section 9.3).
    """
    engine = SubstitutionEngine(FIXTURES_PATH)
    fake_upstream = FakeUpstreamClient()
    pipeline = GatewayPipeline(engine=engine, upstream=fake_upstream)

    await pipeline.execute_chat(
        messages=[
            {"role": "user", "content": "Priya Sharma called."},
            {"role": "user", "content": "Priya Sharma called again."},
        ],
        context=create_request_context(),
        model="gpt-4o",
        stream=False,
    )

    sent = [m["content"] for m in fake_upstream.last_messages]
    assert sent[0].replace("called.", "") .strip() == sent[1].replace("called again.", "").strip()
