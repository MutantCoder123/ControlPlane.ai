"""The event vocabulary the demo surface speaks.

ONE RULE, AND EVERYTHING ELSE FOLLOWS FROM IT
---------------------------------------------
    The UI renders events. It never computes anything the backend computed.

The build this replaces broke that rule twice: the browser re-derived
placeholders with its own regex (a live D15 - it hardcoded a format
CONTRACTS section 4 says only Track A owns), and the server re-implemented
the commit-point buffer in three lines while the real P4 sat unused two
directories away.

Both are the same mistake, and the cost is the same: what a judge sees on
screen stops being evidence about this repo and becomes evidence about the
renderer. So every number in the dashboard arrives as a field on one of these
events, emitted by the module that actually produced it.

THE INSIDE / OUTSIDE ENVELOPE
-----------------------------
Events carry a `side`: "inside" for anything containing real values, "outside"
for anything the provider could legitimately see. The dashboard renders inside
data only on the left of the boundary line and outside data only on the right.

That is a demo affordance, not a security control - the real control is that
`dispatch.text` never contains a mapped value in the first place, which
`leak_check` asserts on every request. But it means a screenshot of the right
half of the screen is, by construction, the provider's view.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from typing import Any

#: Stages, in the order a healthy request produces them.
REQUEST_OPEN = "request.open"
SCAN_INBOUND = "scan.inbound"
DECISION = "decision"
DISPATCH = "dispatch"
STREAM_RAW = "stream.raw"
BUFFER_HOLD = "buffer.hold"
BUFFER_RELEASE = "buffer.release"
RESTORE = "restore"
BLOCK = "block"
ANSWER_DONE = "answer.done"
QUALITY_FINDING = "quality.finding"
QUALITY_DONE = "quality.done"
COST = "cost"
AUDIT_APPEND = "audit.append"
SESSION_RISK = "session.risk"
ERROR = "error"
DONE = "done"


@dataclass
class EventStream:
    """Sequences and timestamps events so the UI can build a real timeline.

    `t_ms` is milliseconds since the request opened, not a wall clock. The
    tape at the bottom of the dashboard is the honest record of how long each
    stage took, and it is the thing to point at when someone asks what the
    gateway costs in latency (D17).
    """

    started: float = field(default_factory=time.perf_counter)
    seq: int = 0

    def emit(self, stage: str, *, side: str = "meta", **payload: Any) -> dict:
        self.seq += 1
        return {
            "seq": self.seq,
            "t_ms": round((time.perf_counter() - self.started) * 1000, 2),
            "stage": stage,
            "side": side,
            **payload,
        }

    @staticmethod
    def sse(event: dict) -> str:
        """One event as a Server-Sent Event frame.

        Named after the stage so a client can attach per-stage listeners, and
        JSON-encoded on ONE line - the previous build's client parsed frames
        with `/event: (.*)\\ndata: (.*)/`, which silently drops any payload
        containing a newline, and model output contains newlines constantly.
        """
        return f"event: {event['stage']}\ndata: {json.dumps(event, default=str)}\n\n"


def finding_payload(finding) -> dict:
    """A `Finding` flattened for the wire.

    Carries `span` because the dashboard underlines the exact characters that
    matched, and `record_ref` because *"matched customer record 44219"* rather
    than *"matched a regex"* is the entire differentiator (IDEATION 9.2).
    """
    return {
        "kind": finding.kind,
        "category": finding.category,
        "action": finding.action,
        "confidence": finding.confidence,
        "span": list(finding.span),
        "record_ref": finding.record_ref,
        "placeholder": finding.placeholder,
    }


def decision_payload(decision) -> dict:
    """A `Decision` flattened for the wire, reasons included.

    The per-signal `reason` string is the point. "allow" alone looks like the
    gateway did nothing; "allow - mitigated by substitution" is the product
    working, and they are the same tier.
    """
    return {
        "tier": decision.tier.label,
        "blocked": decision.blocked,
        "needs_human": decision.needs_human,
        "escalations": sorted(set(decision.escalations)),
        "suppressed": decision.suppressed,
        "sampled": decision.sampled,
        "profile": decision.profile,
        "outcomes": [
            {
                "category": o.signal.category,
                "kind": o.signal.kind,
                "confidence": o.signal.confidence,
                "record_ref": o.signal.record_ref,
                "mitigated": o.signal.mitigated,
                "reversible": o.signal.reversible,
                "tier": o.tier.label,
                "reason": o.reason,
            }
            for o in decision.outcomes
        ],
    }


def session_payload(session_id: str, verdict, *, max_records: int, max_agent_steps: int) -> dict:
    """A `SessionVerdict` flattened for the wire - counters and reasons only.

    Never a prompt, never a restored value, never a raw record - the same
    reference-only discipline as the audit log, which is what makes this
    checkable on screen rather than merely claimed (D4).
    """
    c = verdict.counters
    return {
        "session_id": session_id,
        "turns": c.turns,
        "distinct_records": c.distinct_records,
        "agent_steps": c.agent_steps,
        "findings": c.findings,
        "blocks": c.blocks,
        "over_budget": verdict.over_budget,
        "reasons": verdict.reasons,
        "limits": {"max_records_per_session": max_records, "max_agent_steps": max_agent_steps},
    }


def audit_payload(entry) -> dict:
    return {
        "seq": entry.seq,
        "timestamp": entry.timestamp,
        "event": entry.event,
        "entry_hash": entry.entry_hash,
        "prev_hash": entry.prev_hash,
        "payload": entry.payload,
    }
