"""Tests for Upstream Provider Client (P1 / B4).

Verifies FakeUpstreamClient operates entirely offline with zero network and zero API keys.
"""

from __future__ import annotations

import pytest
from controlplane.gateway.upstream import FakeUpstreamClient


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
