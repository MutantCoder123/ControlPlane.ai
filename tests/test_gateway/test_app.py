"""Tests for FastAPI Gateway Server (P1 / B7).

Verifies OpenAI wire compatibility:
- /healthz endpoint
- /v1/chat/completions (streaming and non-streaming)
- /v1/embeddings (D2)
- Unmodified OpenAI SDK client working against the server with only base_url changed.
"""

from __future__ import annotations

import json
import os
import httpx
import openai
import pytest
from starlette.testclient import TestClient

from controlplane.engine.substitute import SubstitutionEngine
from controlplane.gateway.app import create_app
from controlplane.gateway.upstream import FakeUpstreamClient

FIXTURES_PATH = os.path.join(
    os.path.dirname(__file__), "..", "test_engine", "fixtures", "records.jsonl"
)


def test_healthz_endpoint():
    engine = SubstitutionEngine(FIXTURES_PATH)
    fake_upstream = FakeUpstreamClient()
    app = create_app(engine=engine, upstream=fake_upstream, records_path=FIXTURES_PATH)
    client = TestClient(app)

    response = client.get("/healthz")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert data["portion"] == 1
    assert data["governed_records"] > 0


def test_chat_completions_non_streaming():
    engine = SubstitutionEngine(FIXTURES_PATH)
    # Placeholder derived from the engine, never typed (CONTRACTS.md section 4)
    prompt = "Check Priya Sharma account."
    placeholder = engine.scan_inbound(prompt).findings[0].placeholder
    fake_upstream = FakeUpstreamClient(
        canned_response_text=f"Customer {placeholder} has balance 45230."
    )
    app = create_app(engine=engine, upstream=fake_upstream, records_path=FIXTURES_PATH)
    client = TestClient(app)

    payload = {
        "model": "gpt-4o",
        "messages": [{"role": "user", "content": prompt}],
        "stream": False,
    }
    response = client.post("/v1/chat/completions", json=payload)
    assert response.status_code == 200
    data = response.json()

    # Upstream fake received placeholder
    assert fake_upstream.call_count == 1
    assert placeholder in fake_upstream.last_messages[0]["content"]

    # Client received restored content
    content = data["choices"][0]["message"]["content"]
    assert "Customer Priya Sharma has balance 45230." == content


def test_chat_completions_streaming():
    engine = SubstitutionEngine(FIXTURES_PATH)
    fake_upstream = FakeUpstreamClient(
        canned_response_text="Hello Priya Sharma"
    )
    app = create_app(engine=engine, upstream=fake_upstream, records_path=FIXTURES_PATH)
    client = TestClient(app)

    payload = {
        "model": "gpt-4o",
        "messages": [{"role": "user", "content": "Greeting for Priya Sharma"}],
        "stream": True,
    }
    response = client.post("/v1/chat/completions", json=payload)
    assert response.status_code == 200
    assert "text/event-stream" in response.headers["content-type"]
    lines = response.text.split("\n")
    assert any("data: " in line for line in lines)
    assert any("[DONE]" in line for line in lines)


def test_embeddings_endpoint_d2():
    engine = SubstitutionEngine(FIXTURES_PATH)
    fake_upstream = FakeUpstreamClient()
    app = create_app(engine=engine, upstream=fake_upstream, records_path=FIXTURES_PATH)
    client = TestClient(app)

    payload = {
        "model": "text-embedding-3-small",
        "input": ["Document regarding Priya Sharma and internal policy"],
    }
    response = client.post("/v1/embeddings", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert data["object"] == "list"
    assert len(data["data"]) == 1
    assert len(data["data"][0]["embedding"]) == 8


@pytest.mark.anyio
async def test_openai_client_with_only_base_url_changed():
    """Wire compatibility proof: Unmodified OpenAI Python SDK client."""
    engine = SubstitutionEngine(FIXTURES_PATH)
    prompt = "Please verify customer Priya Sharma."
    placeholder = engine.scan_inbound(prompt).findings[0].placeholder
    fake_upstream = FakeUpstreamClient(
        canned_response_text=f"Processed request for {placeholder} successfully."
    )
    app = create_app(engine=engine, upstream=fake_upstream, records_path=FIXTURES_PATH)

    # Use unmodified AsyncOpenAI client with ASGITransport pointing at our FastAPI app
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver/v1") as http_client:
        openai_client = openai.AsyncOpenAI(
            base_url="http://testserver/v1",
            api_key="test-api-key",
            http_client=http_client,
        )

        completion = await openai_client.chat.completions.create(
            model="gpt-4o",
            messages=[{"role": "user", "content": prompt}],
        )

        assert completion.choices[0].message.content == "Processed request for Priya Sharma successfully."

