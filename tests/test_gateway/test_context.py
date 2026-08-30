"""Tests for Request Context (P1 / B5).

Verifies RequestContext defaults, X-ControlPlane-Profile header overrides, and team extraction.
"""

from __future__ import annotations

from controlplane.gateway.context import RequestContext, create_request_context


def test_profile_defaults_and_header_override():
    # 1. Default profile
    ctx_default = create_request_context(headers={})
    assert ctx_default.profile == "internal-knowledge"
    assert ctx_default.team == "default"

    # 2. Header override
    ctx_custom = create_request_context(
        headers={"X-ControlPlane-Profile": "customer-support", "X-ControlPlane-Team": "support-tier-1"}
    )
    assert ctx_custom.profile == "customer-support"
    assert ctx_custom.team == "support-tier-1"


def test_team_and_auth_extraction():
    ctx = create_request_context(
        headers={"Authorization": "Bearer sk-test-team-key-12345", "X-Request-ID": "custom-req-001"}
    )
    assert ctx.api_key == "sk-test-team-key-12345"
    assert ctx.request_id == "custom-req-001"


def test_api_key_never_appears_in_the_repr():
    """CONTRACTS.md section 3 rule 3: raw secrets stay out of logs.

    RequestContext is a dataclass, so it prints every field by default - and
    the caller's API key is one of them. One `logger.info("ctx=%s", ctx)`
    anywhere downstream and the credential is in the log file, which is the
    concentration risk we sell protection from.
    """
    ctx = RequestContext(api_key="sk-proj-1234567890abcdef1234567890abcdef")

    assert "sk-proj-1234567890abcdef1234567890abcdef" not in repr(ctx)
    # Still readable through the attribute - it is hidden, not removed.
    assert ctx.api_key == "sk-proj-1234567890abcdef1234567890abcdef"
