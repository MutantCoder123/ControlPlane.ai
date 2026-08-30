"""Per-request context - TRACK B owns this.

Carries request id, key -> team, profile name, timings, token counts, findings.

`profile` is still a PASSTHROUGH LABEL here, but the names are no longer
arbitrary: the policy engine landed while this file was offline, and the three
profiles it compiles are customer-support, internal-knowledge and
decision-support (controlplane/policy/profiles/). The default below matches one
of them, because PolicyStore.profile_for() raises PolicyError on an unknown
name rather than falling back to something permissive - so a stale name like
the old "internal-assistant" would fail closed the moment it is wired.

NOT WIRED YET: resolving this string through PolicyStore, so the profile
actually selects checks and buffering. That changes request semantics (an
unknown profile has to become an HTTP error) and belongs with the decision
engine, not with the spine.
# not implemented in Portion 1 - see CONTRACTS.md section 6a and BUILD-PLAN.md P2
"""

from __future__ import annotations

from dataclasses import dataclass, field
import time
import uuid
from typing import Any

from controlplane.engine.api import Finding

# profile is a passthrough label; PolicyStore resolution is not wired yet.
# The valid names are the three in controlplane/policy/profiles/.
# not implemented in Portion 1 — see CONTRACTS.md section 6a


@dataclass
class RequestContext:
    """Per-request contextual metadata throughout the gateway pipeline."""

    request_id: str = field(default_factory=lambda: f"req-{uuid.uuid4().hex[:12]}")
    # repr=False: this is a dataclass, so it prints every field by default,
    # and one logger.info("ctx=%s", ctx) downstream would put the caller's
    # credential in a log file. CONTRACTS.md section 3 rule 3.
    api_key: str | None = field(default=None, repr=False)
    team: str = "default"
    profile: str = "internal-knowledge"
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
    default_profile: str = "internal-knowledge",
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
