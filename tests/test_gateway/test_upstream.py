"""Tests for Upstream Provider Client (P1 / B4).

Verifies FakeUpstreamClient operates entirely offline with zero network and zero API keys.
"""

from __future__ import annotations

import pytest
import httpx

from controlplane.gateway.upstream import FakeUpstreamClient, HttpUpstreamClient


@pytest.mark.anyio
async def test_fake_provider_needs_no_network():
    fake = FakeUpstreamClient()
    messages = [{"role": "user", "content": "Hello control plane"}]

    # 1. Non-streaming
    res = await fake.chat_completion(messages=messages, model="gpt-4o", stream=False)
    assert fake.call_count == 1
    assert "choices" in res
    assert len(res["choices"]) == 1
    assert "Hello control plane" in res["choices"][0]["message"]["content"]

    # 2. Streaming
    stream_gen = await fake.chat_completion(messages=messages, model="gpt-4o", stream=True)
    assert fake.call_count == 2
    chunks = []
    async for chunk in stream_gen:
        chunks.append(chunk)
    assert len(chunks) > 0
    full_streamed = "".join(c["choices"][0]["delta"].get("content", "") for c in chunks)
    assert "Hello control plane" in full_streamed

    # 3. Embeddings
    emb_res = await fake.embeddings(input_data=["Document text 1", "Document text 2"])
    assert fake.embeddings_call_count == 1
    assert len(emb_res["data"]) == 2
    assert len(emb_res["data"][0]["embedding"]) == 8


@pytest.mark.anyio
async def test_streaming_client_is_not_closed_before_the_stream_is_read():
    """The real provider path must survive being iterated.

    `return stream_generator()` from inside `async with httpx.AsyncClient(...)`
    closes the client on the way out, so the first `.stream()` call raised
    "Cannot send a request, as the client has been closed." Every test injected
    the fake, so this would have failed for the first time on stage, with a
    real key, in front of the judges.

    No network here: the request goes to a closed port, so a connection error
    is the PASS. A RuntimeError about a closed client is the regression.
    """
    client = HttpUpstreamClient(base_url="http://127.0.0.1:9/v1", api_key="not-used")
    stream = await client.chat_completion(
        [{"role": "user", "content": "hello"}], stream=True
    )

    with pytest.raises(httpx.HTTPError):
        async for _ in stream:
            pass
