"""Which profile fields actually change behaviour, and which are declared only.

WHY THIS FILE EXISTS
--------------------
An audit on 2026-09-02 (EXPLAINED.md section 8.2) found six profile fields
displayed on the dashboard that no code read. A viewer had no way to tell them
apart from the ones that worked, which is the D23 failure in its most
expensive form: not a missing feature, a *claimed* one.

Cleaning that up once would not stop it happening again. So the state of every
field is declared here, in one place, and `test_enforcement.py` fails the build
if a new field is added to `Profile` without an entry. A gap can still exist -
it just cannot be silent.

HOW TO USE IT
-------------
When you wire a field up, flip its entry to `ENFORCED` in the same commit that
does the wiring. If those two ever drift apart, this file is the lie.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class FieldState:
    enforced: bool
    note: str


def _on(note: str) -> FieldState:
    return FieldState(True, note)


def _off(note: str) -> FieldState:
    return FieldState(False, note)


#: Keyed by "section.field", or the bare field name for top-level ones.
#: Every field on `Profile` and its nested policies must appear here.
ENFORCEMENT: dict[str, FieldState] = {
    # -- identity -------------------------------------------------------
    "name": _on("selects the profile"),
    "description": _on("shown on the Profiles page"),
    "geography": _on("selects the jurisdiction floor clamped in at compile time (D29)"),
    "audit_level": _off("declared only - GAP-CLOSURE-PLAN phase 2.4"),
    "fingerprint": _on("content hash; proves two servers run identical rules"),

    # -- inbound --------------------------------------------------------
    "inbound.substitute_pii": _off(
        "declared only - phase 2.1. Compile-time it already demands a written "
        "waiver, so it cannot be flipped silently; the engine does not yet act on it"
    ),
    "inbound.block_credentials": _on(
        "the compiler refuses to build a profile that disables it (IDEATION 9.5)"
    ),
    "inbound.known_value_matching": _off("declared only - phase 2.1"),
    "inbound.pii_waiver_reason": _on(
        "required when substitute_pii is false; travels into the fingerprint"
    ),

    # -- outbound -------------------------------------------------------
    "outbound.block_credentials": _on(
        "the compiler refuses to build a profile that disables it (IDEATION 9.6)"
    ),
    "outbound.scan_pii": _off("declared only - phase 2.1"),
    "outbound.cross_tenant_check": _off(
        "declared only - phase 2.2, where it is renamed cross_record_check, "
        "because there is no tenant in the data model. The compiler already "
        "refuses it without scan_pii, so the pair cannot be incoherent"
    ),

    # -- streaming ------------------------------------------------------
    "streaming.mode": _on("interactive buffers to commit points; throughput does not"),
    "streaming.commit_tokens": _on("commit-point trigger in stream/buffer.py"),
    "streaming.commit_ms": _on("commit-point trigger in stream/buffer.py"),
    "streaming.overlap_chars": _on("the seam window that catches a split secret (D5)"),

    # -- decision -------------------------------------------------------
    "decision.block_at": _on("the block threshold in decision/tiers.py"),
    "decision.review_band": _on("the mid-band that escalates irreversible harm"),
    "decision.flag_budget_per_100": _on("caps user-visible flags; can never suppress a block"),
    "decision.always_review": _on("decision-support routes every response to a human"),
    "decision.exempt": _on("reviewer-approved exemptions; credentials can never appear here"),

    # -- quality --------------------------------------------------------
    "quality.hallucination_tier": _off("declared only - phase 4.3 wires tiers 0 and 1"),
    "quality.toxicity_sync": _off("declared only - phase 4.1; toxicity runs async today (D31)"),
    "quality.counterfactual_sample_rate": _off(
        "declared only - phase 4.2; the bias probe is manual-only today (D32)"
    ),

    # -- cost -----------------------------------------------------------
    "cost.cache_enabled": _off(
        "declared only - phase 5.4, narrowed to exact-match caching. "
        "Semantic caching stays unbuilt (D13)"
    ),
    "cost.max_output_tokens": _off("declared only - phase 2.3"),
    "cost.request_budget_usd": _off("declared only - phase 2.3"),

    # -- session --------------------------------------------------------
    "session.max_records_per_session": _on("cumulative disclosure budget (D4)"),
    "session.max_agent_steps": _on("agent-step budget (D4)"),
}


def state(key: str) -> FieldState:
    """The state of one field, or a loud placeholder if it was never declared."""
    return ENFORCEMENT.get(key, _off("UNDECLARED - see policy/enforcement.py"))


def as_payload() -> dict[str, dict]:
    """Wire format for `/demo/profiles`, so the dashboard can grey out what is
    declared but not yet doing anything."""
    return {k: {"enforced": v.enforced, "note": v.note} for k, v in ENFORCEMENT.items()}


def unenforced() -> list[str]:
    return sorted(k for k, v in ENFORCEMENT.items() if not v.enforced)
