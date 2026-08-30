"""Per-request context - TRACK B owns this.

Carries request id, key -> team, profile name, timings, token counts, findings.

Portion 1: `profile` is a PASSTHROUGH LABEL ONLY. The compiled policy
artefact, hot-swap and per-profile check selection land in P2 - see
BUILD-PLAN.md. Do not build the profile engine here.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import time
import uuid
from typing import Any

from controlplane.engine.api import Finding

# Portion 1: profile is a passthrough label only.
# The compiled policy artefact + hot-swap lands in P2 — see BUILD-PLAN.md.
# not implemented in Portion 1 — see BUILD-PLAN.md P2


@dataclass
class RequestContext:
    """Per-request contextual metadata throughout the gateway pipeline."""

    request_id: str = field(default_factory=lambda: f"req-{uuid.uuid4().hex[:12]}")
    api_key: str | None = None
    team: str = "default"
    profile: str = "internal-assistant"
    start_time: float = field(default_factory=time.time)
    timings: dict[str, float] = field(default_factory=dict)
    token_counts: dict[str, int] = field(default_factory=dict)
    findings: list[Finding] = field(default_factory=list)
    cost_usd: float = 0.0

    def record_timing(self, stage: str, duration_ms: float) -> None:
        self.timings[stage] = duration_ms


def create_request_context(
    headers: dict[str, str] | None = None,
    api_key: str | None = None,
    default_profile: str = "internal-assistant",
) -> RequestContext:
    """Factory creating RequestContext from HTTP headers and auth information."""
    headers = headers or {}
    
    # Case-insensitive header lookup
    norm_headers = {k.lower(): v for k, v in headers.items()}
    
    # Profile selection: header override or default
    profile = norm_headers.get("x-controlplane-profile", default_profile)
    team = norm_headers.get("x-controlplane-team", "default")
    req_id = norm_headers.get("x-request-id") or f"req-{uuid.uuid4().hex[:12]}"

    if not api_key:
        auth_header = norm_headers.get("authorization", "")
        if auth_header.startswith("Bearer "):
            api_key = auth_header[7:].strip()

    return RequestContext(
        request_id=req_id,
        api_key=api_key,
        team=team,
        profile=profile,
    )
