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
from controlplane.policy.profile import Profile
from controlplane.policy.store import PolicyStore
from controlplane.stream.buffer import CommitPointBuffer


class GatewayPipeline:
    """Orchestrates the inbound scan -> pre-dispatch gate -> upstream -> restore pipeline."""

    def __init__(
        self,
        engine: SubstitutionEngine,
        upstream: UpstreamClient,
        policy_store: PolicyStore | None = None,
    ):
        self.engine = engine
        self.upstream = upstream
        #: Optional so a test can build a pipeline with nothing else wired.
        #: When absent the profile falls back to library defaults, which is
        #: honest rather than profile-driven - create_app always supplies one.
        self.policy_store = policy_store

    def _profile_for(self, name: str) -> Profile:
        """Resolve the request's profile name to a compiled Profile.

        With a store this raises PolicyError on an unknown name rather than
        falling back to something permissive - failing closed on policy is the
        same instinct as failing closed on the scanner (IDEATION section 17).
        """
        if self.policy_store is not None:
            return self.policy_store.profile_for(name)
        return Profile(name=name)

    def _scan_parts(
        self,
        parts: list[Any],
        all_findings: list,
        combined_mapping: dict[str, str],
    ) -> tuple[list[Any], bool, str | None]:
        """Scan every text part of a multi-part message.

        Non-text parts (image_url, input_audio) are passed through: this tier
        reads text, and pretending to inspect an image would be a claim we
        cannot support.
        # not implemented in Portion 1 - non-text parts are out of scope, see
        # DRAWBACK.md D10
        """
        out: list[Any] = []
        for part in parts:
            if isinstance(part, str):
                text, key = part, None
            elif isinstance(part, dict) and isinstance(part.get("text"), str):
                text, key = part["text"], "text"
            else:
                out.append(part)
                continue

            scan_res = self.engine.scan_inbound(text)
            all_findings.extend(scan_res.findings)
            if scan_res.blocked:
                return out, True, scan_res.block_reason
            combined_mapping.update(scan_res.mapping)
            out.append(scan_res.text if key is None else {**part, key: scan_res.text})
        return out, False, None

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

        # Resolve the profile FIRST, before scanning and long before dispatch.
        # An unknown profile is a refusal, and refusals should cost nothing
        # (IDEATION section 8) - so it happens before any work, and on every
        # path rather than only the streaming one.
        profile = self._profile_for(context.profile)

        # 1. Extract prompt text from messages and scan inbound
        # We transform user messages while preserving system/assistant structure
        transformed_messages: list[dict[str, Any]] = []
        combined_mapping: dict[str, str] = {}
        all_findings = []

        is_blocked = False
        block_reason = None

        for msg in messages:
            if msg.get("role") != "user":
                transformed_messages.append(msg)
                continue

            content = msg.get("content", "")

            if isinstance(content, str):
                scan_res: ScanResult = self.engine.scan_inbound(content)
                all_findings.extend(scan_res.findings)
                if scan_res.blocked:
                    is_blocked = True
                    block_reason = scan_res.block_reason
                    break
                combined_mapping.update(scan_res.mapping)
                transformed_messages.append({**msg, "content": scan_res.text})
                continue

            if isinstance(content, list):
                # The OpenAI SDK sends content as a list of parts for every
                # multimodal and most tool-augmented calls. Guarding on
                # `isinstance(content, str)` sent this whole shape upstream
                # UNSCANNED - real names and live keys included - and nothing
                # in the response said so. An unscanned path is worse than a
                # refused one, because silence reads as safety.
                scanned_parts, part_blocked, part_reason = self._scan_parts(
                    content, all_findings, combined_mapping
                )
                if part_blocked:
                    is_blocked = True
                    block_reason = part_reason
                    break
                transformed_messages.append({**msg, "content": scanned_parts})
                continue

            # Some shape we do not understand. Fail closed (IDEATION section 17):
            # the credential/PII checker blocks when it cannot do its job, because
            # a broken app beats a leak.
            is_blocked = True
            block_reason = (
                f"unscannable message content of type {type(content).__name__}"
            )
            break

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
                "provider": getattr(self.upstream, "name", "unknown"),
                "restored_count": restore_res.restored,
                "unrestored": restore_res.unrestored,
                "profile": context.profile,
                "team": context.team,
                "timings": context.timings,
            }
            return upstream_res

        # 5. Streaming response, through the commit-point buffer.
        #
        # The seam my brief told me to leave is now filled: accumulate, scan,
        # release - never the other way round (CONTRACTS.md section 6a).
        #
        # This path used to build `accumulated_response` and throw it away,
        # yielding the upstream chunks untouched, so the reader watched
        # placeholders appear on screen. Restoring each chunk on its own would
        # not have fixed it either: the fake emits word by word and a real
        # provider emits token by token, so a placeholder routinely arrives in
        # pieces and matches nothing. Holding a boundary region is the point.
        async def streaming_pipeline() -> AsyncIterator[dict[str, Any]]:
            buffer = CommitPointBuffer(
                profile,
                self.engine.scan_outbound,
                restore=self.engine.restore,
                mapping=combined_mapping,
            )
            template: dict[str, Any] | None = None

            def as_chunk(text: str, finish: str | None) -> dict[str, Any]:
                base = template or {
                    "id": f"chatcmpl-{context.request_id}",
                    "object": "chat.completion.chunk",
                    "created": int(time.time()),
                    "model": model,
                }
                return {
                    "id": base.get("id"),
                    "object": "chat.completion.chunk",
                    "created": base.get("created"),
                    "model": base.get("model", model),
                    "choices": [
                        {
                            "index": 0,
                            "delta": {"content": text} if text else {},
                            "finish_reason": finish,
                        }
                    ],
                }

            stopped = False
            async for chunk in upstream_res:  # type: ignore
                if template is None:
                    template = chunk
                delta = ""
                if chunk.get("choices"):
                    delta = chunk["choices"][0].get("delta", {}).get("content") or ""
                for release in buffer.feed(delta):
                    if release.blocked:
                        # Irreversible harm: it is not on screen yet, and this
                        # is the one moment it can still be stopped.
                        yield as_chunk("", "content_filter")
                        stopped = True
                        break
                    yield as_chunk(release.text, None)
                if stopped:
                    return

            for release in buffer.flush():
                if release.blocked:
                    yield as_chunk("", "content_filter")
                    return
                yield as_chunk(release.text, None)

            yield as_chunk("", "stop")

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
