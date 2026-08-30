"""Provider client - TRACK B owns this.

Async HTTP to the real provider, behind a small interface so a fake can be
injected. The test suite must not require a live API key or network.

D3, stated honestly: "one line" is literal for OpenAI-compatible endpoints,
and a config block for Bedrock (SigV4) and Azure OpenAI (deployment names).
Build the OpenAI-compatible path; the other two are a README config concern.
Do not overclaim.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
import json
import time
from typing import Any, AsyncIterator
import uuid
import httpx


class UpstreamClient(ABC):
    """Abstract interface for LLM provider client."""

    @abstractmethod
    async def chat_completion(
        self,
        messages: list[dict[str, Any]],
        model: str = "gpt-4o",
        stream: bool = False,
        **kwargs: Any,
    ) -> dict[str, Any] | AsyncIterator[dict[str, Any]]:
        """Perform chat completion (streaming or non-streaming)."""
        pass

    @abstractmethod
    async def embeddings(
        self,
        input_data: str | list[str],
        model: str = "text-embedding-3-small",
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Generate embeddings for input text (D2)."""
        pass


class HttpUpstreamClient(UpstreamClient):
    """Real HTTP client connecting to OpenAI or compatible API endpoints."""

    def __init__(
        self,
        base_url: str = "https://api.openai.com/v1",
        api_key: str | None = None,
        timeout: float = 60.0,
    ):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key or ""
        self.timeout = timeout

    async def chat_completion(
        self,
        messages: list[dict[str, Any]],
        model: str = "gpt-4o",
        stream: bool = False,
        **kwargs: Any,
    ) -> dict[str, Any] | AsyncIterator[dict[str, Any]]:
        headers = {"Authorization": f"Bearer {self.api_key}"}
        payload = {"model": model, "messages": messages, "stream": stream, **kwargs}

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            if not stream:
                response = await client.post(
                    f"{self.base_url}/chat/completions",
                    json=payload,
                    headers=headers,
                )
                response.raise_for_status()
                return response.json()
            else:
                # Streaming generator
                async def stream_generator() -> AsyncIterator[dict[str, Any]]:
                    async with client.stream(
                        "POST",
                        f"{self.base_url}/chat/completions",
                        json=payload,
                        headers=headers,
                    ) as resp:
                        resp.raise_for_status()
                        async for line in resp.aiter_lines():
                            if line.startswith("data: ") and line.strip() != "data: [DONE]":
                                chunk_json = json.loads(line[6:])
                                yield chunk_json

                return stream_generator()

    async def embeddings(
        self,
        input_data: str | list[str],
        model: str = "text-embedding-3-small",
        **kwargs: Any,
    ) -> dict[str, Any]:
        headers = {"Authorization": f"Bearer {self.api_key}"}
        payload = {"model": model, "input": input_data, **kwargs}
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.post(
                f"{self.base_url}/embeddings",
                json=payload,
                headers=headers,
            )
            response.raise_for_status()
            return response.json()


class FakeUpstreamClient(UpstreamClient):
    """Test-injectable fake upstream provider requiring zero network and zero API keys."""

    def __init__(self, canned_response_text: str | None = None):
        self.call_count: int = 0
        self.embeddings_call_count: int = 0
        self.last_messages: list[dict[str, Any]] | None = None
        self.last_model: str | None = None
        self.canned_response_text = canned_response_text

    async def chat_completion(
        self,
        messages: list[dict[str, Any]],
        model: str = "gpt-4o",
        stream: bool = False,
        **kwargs: Any,
    ) -> dict[str, Any] | AsyncIterator[dict[str, Any]]:
        self.call_count += 1
        self.last_messages = messages
        self.last_model = model

        # Derive response text from last user message if no canned text
        last_user_content = ""
        for m in reversed(messages):
            if m.get("role") == "user":
                last_user_content = str(m.get("content", ""))
                break

        if self.canned_response_text is not None:
            response_content = self.canned_response_text
        else:
            response_content = f"Processed query successfully for: {last_user_content}"

        req_id = f"chatcmpl-{uuid.uuid4().hex[:8]}"
        created = int(time.time())

        if not stream:
            return {
                "id": req_id,
                "object": "chat.completion",
                "created": created,
                "model": model,
                "choices": [
                    {
                        "index": 0,
                        "message": {
                            "role": "assistant",
                            "content": response_content,
                        },
                        "finish_reason": "stop",
                    }
                ],
                "usage": {
                    "prompt_tokens": len(last_user_content.split()),
                    "completion_tokens": len(response_content.split()),
                    "total_tokens": len(last_user_content.split()) + len(response_content.split()),
                },
            }
        else:
            # Streaming generator yielding chunks
            async def fake_stream() -> AsyncIterator[dict[str, Any]]:
                # Split content into words as chunks
                words = response_content.split(" ")
                for i, word in enumerate(words):
                    chunk_text = word + (" " if i < len(words) - 1 else "")
                    yield {
                        "id": req_id,
                        "object": "chat.completion.chunk",
                        "created": created,
                        "model": model,
                        "choices": [
                            {
                                "index": 0,
                                "delta": {"content": chunk_text},
                                "finish_reason": None if i < len(words) - 1 else "stop",
                            }
                        ],
                    }

            return fake_stream()

    async def embeddings(
        self,
        input_data: str | list[str],
        model: str = "text-embedding-3-small",
        **kwargs: Any,
    ) -> dict[str, Any]:
        self.embeddings_call_count += 1
        inputs = [input_data] if isinstance(input_data, str) else input_data
        data = []
        for idx, text_item in enumerate(inputs):
            # Synthetic 8-dimension mock vector
            data.append({
                "object": "embedding",
                "index": idx,
                "embedding": [0.01 * (i + 1) for i in range(8)],
            })

        return {
            "object": "list",
            "data": data,
            "model": model,
            "usage": {"prompt_tokens": sum(len(t.split()) for t in inputs), "total_tokens": sum(len(t.split()) for t in inputs)},
        }
