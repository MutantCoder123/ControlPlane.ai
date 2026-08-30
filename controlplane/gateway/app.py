"""FastAPI server - TRACK B owns this.

Routes:
  POST /v1/chat/completions   streaming and non-streaming
  POST /v1/embeddings         D2 - one extra route. A RAG rollout ships the
                              entire corpus through here at ingestion; a
                              chat-only proxy never sees the largest bulk
                              egress in the deployment.
  GET  /healthz

Wire-compatible with OpenAI: the test that matters is an unmodified `openai`
client with only base_url changed.
"""

from __future__ import annotations

import json
import os
from typing import Any, AsyncIterator
from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field

from controlplane.engine.substitute import SubstitutionEngine
from controlplane.gateway.context import create_request_context
from controlplane.gateway.pipeline import GatewayPipeline
from controlplane.gateway.upstream import FakeUpstreamClient, HttpUpstreamClient, UpstreamClient
from controlplane.seed.generate import DEFAULT_DATA_PATH, generate_seed_records


class ChatMessage(BaseModel):
    role: str
    content: str | list[Any] = ""
    name: str | None = None


class ChatCompletionRequest(BaseModel):
    model: str = "gpt-4o"
    messages: list[ChatMessage]
    stream: bool = False
    temperature: float | None = None
    max_tokens: int | None = None


class EmbeddingRequest(BaseModel):
    model: str = "text-embedding-3-small"
    input: str | list[str]


def create_app(
    engine: SubstitutionEngine | None = None,
    upstream: UpstreamClient | None = None,
    records_path: str | None = None,
) -> FastAPI:
    """Create and configure the FastAPI gateway application."""
    app = FastAPI(title="ControlPlane.ai Gateway", version="0.1.0")

    # Initialize records & engine
    rec_path = records_path or DEFAULT_DATA_PATH
    if not os.path.exists(rec_path):
        generate_seed_records(rec_path)

    sub_engine = engine or SubstitutionEngine(records_path=rec_path)
    
    # Initialize upstream provider (HttpUpstreamClient or Fake if no API key)
    if upstream is not None:
        provider = upstream
    else:
        openai_key = os.getenv("OPENAI_API_KEY")
        if openai_key:
            provider = HttpUpstreamClient(api_key=openai_key)
        else:
            # Fallback to offline fake provider
            provider = FakeUpstreamClient()

    pipeline = GatewayPipeline(engine=sub_engine, upstream=provider)

    @app.get("/healthz")
    async def healthz():
        return {
            "status": "ok",
            "portion": 1,
            "governed_records": sub_engine.store.record_count,
        }

    @app.post("/v1/chat/completions")
    async def chat_completions(req: ChatCompletionRequest, request: Request):
        raw_headers = dict(request.headers)
        auth_header = raw_headers.get("authorization", "")
        api_key = auth_header[7:].strip() if auth_header.startswith("Bearer ") else None

        ctx = create_request_context(
            headers=raw_headers,
            api_key=api_key,
        )

        messages_dict = [m.model_dump() for m in req.messages]

        result = await pipeline.execute_chat(
            messages=messages_dict,
            context=ctx,
            model=req.model,
            stream=req.stream,
        )

        if not req.stream:
            return JSONResponse(content=result)

        # Handle streaming responses as SSE
        async def event_generator() -> AsyncIterator[str]:
            async for chunk in result:  # type: ignore
                yield f"data: {json.dumps(chunk)}\n\n"
            yield "data: [DONE]\n\n"

        return StreamingResponse(event_generator(), media_type="text/event-stream")

    @app.post("/v1/embeddings")
    async def embeddings(req: EmbeddingRequest, request: Request):
        raw_headers = dict(request.headers)
        ctx = create_request_context(headers=raw_headers)
        result = await pipeline.execute_embeddings(
            input_data=req.input,
            context=ctx,
            model=req.model,
        )
        return JSONResponse(content=result)

    return app


# Default app instance
app = create_app()


if __name__ == "__main__":
    import uvicorn
    print("Starting ControlPlane.ai Gateway on port 8000...")
    uvicorn.run(app, host="0.0.0.0", port=8000)
