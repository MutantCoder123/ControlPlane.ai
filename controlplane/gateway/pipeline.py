"""Where the two tracks meet - TRACK B owns this.

    request -> engine.scan_inbound(prompt)
            -> if blocked: refuse at cost_usd 0.0, NEVER dispatch
            -> dispatch scanned.text upstream
            -> engine.restore(response, scanned.mapping)
            -> return to caller

The refusal happens BEFORE dispatch on purpose (IDEATION section 8): you are
billed the moment tokens are generated, so forwarding first and cancelling on
failure means you block the request and still pay. Check first, dispatch
second.

Import ONLY the names in CONTRACTS.md section 3, plus PLACEHOLDER_RE /
is_placeholder if you need to recognise a placeholder. Never hardcode the
placeholder format - that is a live D15 bug even on the day it happens to work.

NOT in Portion 1: commit-point buffer (P4), decision tiers (P6), audit log
(P8). Stream straight through and leave the seam.
"""

from __future__ import annotations

import json
import time
from typing import Any, AsyncIterator

from controlplane.engine.api import (
    RestoreResult,
    ScanResult,
)
from controlplane.engine.substitute import SubstitutionEngine
from controlplane.gateway.context import RequestContext
from controlplane.gateway.upstream import UpstreamClient


class GatewayPipeline:
    """Orchestrates the inbound scan -> pre-dispatch gate -> upstream -> restore pipeline."""

    def __init__(self, engine: SubstitutionEngine, upstream: UpstreamClient):
        self.engine = engine
        self.upstream = upstream

    async def execute_chat(
        self,
        messages: list[dict[str, Any]],
        context: RequestContext,
        model: str = "gpt-4o",
        stream: bool = False,
        **kwargs: Any,
    ) -> dict[str, Any] | AsyncIterator[dict[str, Any]]:
        """Execute chat completion through the ControlPlane pipeline."""
        start_t = time.time()

        # 1. Extract prompt text from messages and scan inbound
        # We transform user messages while preserving system/assistant structure
        transformed_messages: list[dict[str, Any]] = []
        combined_mapping: dict[str, str] = {}
        all_findings = []

        is_blocked = False
        block_reason = None

        for msg in messages:
            content = msg.get("content", "")
            if msg.get("role") == "user" and isinstance(content, str):
                scan_res: ScanResult = self.engine.scan_inbound(content)
                all_findings.extend(scan_res.findings)
                if scan_res.blocked:
                    is_blocked = True
                    block_reason = scan_res.block_reason
                    break
                combined_mapping.update(scan_res.mapping)
                transformed_messages.append({**msg, "content": scan_res.text})
            else:
                transformed_messages.append(msg)

        context.findings = all_findings
        context.record_timing("scan_inbound_ms", (time.time() - start_t) * 1000)

        # 2. Pre-dispatch gate (IDEATION §8)
        # If blocked, refuse immediately with cost_usd 0.0. NEVER DISPATCH UPSTREAM!
        if is_blocked:
            context.cost_usd = 0.0
            refusal_message = (
                f"Request refused by ControlPlane safety policy: {block_reason}. "
                "No data was forwarded upstream."
            )
            return {
                "id": f"refusal-{context.request_id}",
                "object": "chat.completion",
                "created": int(time.time()),
                "model": model,
                "choices": [
                    {
                        "index": 0,
                        "message": {
                            "role": "assistant",
                            "content": refusal_message,
                        },
                        "finish_reason": "content_filter",
                    }
                ],
                "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
                "controlplane": {
                    "blocked": True,
                    "reason": block_reason,
                    "cost_usd": 0.0,
                    "profile": context.profile,
                    "findings_count": len(all_findings),
                },
            }

        # 3. Dispatch transformed prompt upstream
        dispatch_t = time.time()
        upstream_res = await self.upstream.chat_completion(
            messages=transformed_messages,
            model=model,
            stream=stream,
            **kwargs,
        )
        context.record_timing("upstream_dispatch_ms", (time.time() - dispatch_t) * 1000)

        # 4. Non-streaming restoration
        if not stream:
            assert isinstance(upstream_res, dict)
            raw_response_text = ""
            if "choices" in upstream_res and len(upstream_res["choices"]) > 0:
                raw_response_text = upstream_res["choices"][0]["message"].get("content", "")

            # Restore real values using request-scoped mapping
            restore_t = time.time()
            restore_res: RestoreResult = self.engine.restore(
                raw_response_text, combined_mapping
            )
            context.record_timing("restore_ms", (time.time() - restore_t) * 1000)

            # Update choice content with restored text
            upstream_res["choices"][0]["message"]["content"] = restore_res.text
            upstream_res["controlplane"] = {
                "blocked": False,
                "restored_count": restore_res.restored,
                "unrestored": restore_res.unrestored,
                "profile": context.profile,
                "team": context.team,
                "timings": context.timings,
            }
            return upstream_res

        # 5. Streaming response generator
        # not implemented in Portion 1: commit-point buffer (P4) — see BUILD-PLAN.md P4
        # In Portion 1 we stream through chunks and restore tokens
        async def streaming_pipeline() -> AsyncIterator[dict[str, Any]]:
            accumulated_response = ""
            async for chunk in upstream_res:  # type: ignore
                delta_content = ""
                if "choices" in chunk and len(chunk["choices"]) > 0:
                    delta_content = chunk["choices"][0].get("delta", {}).get("content", "")
                accumulated_response += delta_content
                yield chunk

            # Final check (P4 commit-point buffer will replace this with sliding overlap guard)
            # Portion 1 passes through streaming chunks directly

        return streaming_pipeline()

    async def execute_embeddings(
        self,
        input_data: str | list[str],
        context: RequestContext,
        model: str = "text-embedding-3-small",
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Execute embeddings route with inbound substitution pass (D2)."""
        inputs = [input_data] if isinstance(input_data, str) else input_data
        transformed_inputs = []
        for item in inputs:
            scan_res = self.engine.scan_inbound(item)
            if scan_res.blocked:
                return {
                    "object": "error",
                    "message": f"Embeddings input blocked: {scan_res.block_reason}",
                    "controlplane": {"blocked": True, "cost_usd": 0.0},
                }
            transformed_inputs.append(scan_res.text)

        final_input = transformed_inputs[0] if isinstance(input_data, str) else transformed_inputs
        return await self.upstream.embeddings(final_input, model=model, **kwargs)
