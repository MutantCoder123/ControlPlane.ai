"""Public types for the substitution engine.

This module is THE contract between Track A (engine) and Track B (gateway).
It is specified in CONTRACTS.md §3 — do not change a field here without
changing CONTRACTS.md first and telling the other track.

Track B imports only from this module and from `placeholders`.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Finding:
    """One sensitive value located in a piece of text.

    `span` refers to offsets in the ORIGINAL text, not the transformed text —
    the gateway needs those offsets for the audit entry.

    `record_ref` is what turns the audit line from "matched a regex" into
    "matched customer record 44219" (IDEATION §9.2). It is None for the
    pattern tier, and for ungoverned records (D28).
    """

    kind: str                       # "known_value" | "pattern"
    category: str                   # "customer_name" | "api_key" | ...
    action: str                     # "substitute" | "block"
    span: tuple[int, int]
    confidence: float               # 1.0 for known-value and checksum-verified
    record_ref: str | None = None
    placeholder: str | None = None  # None when action == "block"


@dataclass
class ScanResult:
    """Outcome of scanning one piece of text.

    `mapping` is REQUEST-SCOPED. It is created per request, handed back to
    restore(), then dropped. Nothing persists it, ever — statelessness is the
    whole positioning (IDEATION §3).
    """

    text: str
    findings: list[Finding] = field(default_factory=list)
    mapping: dict[str, str] = field(default_factory=dict)
    blocked: bool = False
    block_reason: str | None = None


@dataclass
class RestoreResult:
    """Outcome of putting real values back into a model response.

    `unrestored` is the D15 alarm. If this list is ever non-empty during the
    demo, the placeholder format did not survive the round trip and the
    strongest fifteen seconds of the pitch is about to show artefacts on
    stage. Treat a non-empty list as a failing test, not a warning.
    """

    text: str
    restored: int = 0
    unrestored: list[str] = field(default_factory=list)


@dataclass
class EngineConfig:
    """Tuning knobs. Deliberately small in Portion 1.

    Per-profile configuration (which checks run, thresholds, flag budgets)
    is NOT here — that is the compiled policy artefact in P2.
    See BUILD-PLAN.md.
    """

    bloom_capacity: int = 100_000
    bloom_error_rate: float = 0.001
    min_ngram: int = 1
    max_ngram: int = 3
