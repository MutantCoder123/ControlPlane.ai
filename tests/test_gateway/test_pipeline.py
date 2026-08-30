"""Tests for Gateway Pipeline (P1 / B6).

Verifies IDEATION §8: credential refusal BEFORE dispatch with cost_usd 0.0 (fake provider never called).
Verifies end-to-end substitution -> dispatch -> restoration round trip.
"""

from __future__ import annotations

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
