"""Hash-chained audit log.

IDEATION section 18. Each entry carries a fingerprint of the previous one, so
editing any record breaks every hash after it. Cheap to build, and demoable:
edit one row live and watch verification fail on stage.

WHAT WE STORE, AND WHAT WE REFUSE TO
------------------------------------
Hashes and already-redacted text. Never a raw sensitive value. Otherwise the
compliance tool becomes the largest concentration of leaked data in the
company - we would have rebuilt exactly the risk we sell protection from.

That is not left to caller discipline. `append` runs a guard over every
payload and raises on anything that looks like a live credential or a
recognisable identifier. A convention nobody enforces is a convention that
gets broken at 2am before a demo.

The audit line that matters is "matched customer record 44219", not the
customer's name (IDEATION section 9.2) - a record reference is a pointer into
a system that already holds the data under its own controls, which is
precisely why it is safe to write down.

D14 - the chain lives in process memory. Tamper-EVIDENCE is real: any edit
invalidates the chain. Tamper-PROOFING is not: an attacker who owns the
process can rewrite the whole chain and recompute every hash. Production
needs append-only storage with the head anchored somewhere we do not control.
Stated openly rather than implied.
"""

from __future__ import annotations

import hashlib
import json
import re
import threading
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone

GENESIS = "0" * 64


class AuditIntegrityError(RuntimeError):
    """A payload that must not be written to the log."""


# Patterns that must never reach the audit log. Deliberately the credential
# shapes plus long digit runs - the things that are exploitable forever if
# they leak (IDEATION section 9.1).
_FORBIDDEN = [
    ("api_key", re.compile(r"\b(?:sk-|sk-ant-|ghp_|gho_|ghs_|xox[baprs]-)[A-Za-z0-9_-]{10,}")),
    ("aws_key", re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b")),
    ("jwt", re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.")),
    ("private_key", re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH |PGP )?PRIVATE KEY-----")),
    ("long_digit_run", re.compile(r"\b\d{12,19}\b")),
]


def text_fingerprint(text: str) -> str:
    """Hash of a piece of text, for proving what was processed without keeping it.

    Lets an entry answer "was this the prompt you saw?" - the auditor supplies
    the text and we compare - while holding nothing that is useful to steal.
    """
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _guard(payload: dict) -> None:
    blob = json.dumps(payload, sort_keys=True, default=str)
    for label, pattern in _FORBIDDEN:
        if pattern.search(blob):
            raise AuditIntegrityError(
                f"refusing to write {label} to the audit log - store a fingerprint "
                f"or a record reference instead (IDEATION section 18)"
            )


@dataclass(frozen=True)
class AuditEntry:
    seq: int
    timestamp: str
    event: str
    payload: dict
    prev_hash: str
    entry_hash: str = ""

    def compute_hash(self) -> str:
        body = json.dumps(
            {
                "seq": self.seq,
                "timestamp": self.timestamp,
                "event": self.event,
                "payload": self.payload,
                "prev_hash": self.prev_hash,
            },
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        )
        return hashlib.sha256(body.encode("utf-8")).hexdigest()

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class VerificationResult:
    ok: bool
    entries: int
    broken_at: int | None = None
    reason: str | None = None

    def __bool__(self) -> bool:
        return self.ok


class AuditLog:
    """Append-only in this process, tamper-evident by construction."""

    def __init__(self) -> None:
        self._entries: list[AuditEntry] = []
        self._lock = threading.Lock()

    def append(self, event: str, **payload) -> AuditEntry:
        """Write one entry, chained to the previous.

        Raises `AuditIntegrityError` if the payload carries anything that
        must not be written down. Failing the write is correct: a compliance
        log that quietly stores a secret is worse than one that errors.
        """
        _guard(payload)
        with self._lock:
            prev = self._entries[-1].entry_hash if self._entries else GENESIS
            entry = AuditEntry(
                seq=len(self._entries),
                timestamp=datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
                event=event,
                payload=payload,
                prev_hash=prev,
            )
            entry = AuditEntry(**{**entry.to_dict(), "entry_hash": entry.compute_hash()})
            self._entries.append(entry)
            return entry

    def verify(self) -> VerificationResult:
        """Walk the chain. Any edit anywhere breaks it from that point on."""
        prev = GENESIS
        for i, entry in enumerate(self._entries):
            if entry.seq != i:
                return VerificationResult(False, len(self._entries), i, "sequence number altered")
            if entry.prev_hash != prev:
                return VerificationResult(False, len(self._entries), i, "chain link broken")
            if entry.compute_hash() != entry.entry_hash:
                return VerificationResult(False, len(self._entries), i, "entry contents altered")
            prev = entry.entry_hash
        return VerificationResult(True, len(self._entries))

    # -- reading -----------------------------------------------------------

    @property
    def entries(self) -> list[AuditEntry]:
        return list(self._entries)

    @property
    def head(self) -> str:
        return self._entries[-1].entry_hash if self._entries else GENESIS

    def __len__(self) -> int:
        return len(self._entries)

    def by_event(self, event: str) -> list[AuditEntry]:
        return [e for e in self._entries if e.event == event]

    def export(self) -> str:
        return "\n".join(json.dumps(e.to_dict(), sort_keys=True) for e in self._entries)

    # -- demo affordance ---------------------------------------------------

    def _tamper(self, seq: int, **changes) -> None:
        """Edit a committed record IN PLACE, leaving its hash untouched.

        Exists so demo step 8 can show verification failing on stage. This is
        the only way to mutate the log, it is underscore-private, and it is
        what an attacker with process access would do - which is exactly the
        limitation D14 describes.
        """
        old = self._entries[seq]
        self._entries[seq] = AuditEntry(
            **{**old.to_dict(), **changes, "entry_hash": old.entry_hash}
        )


# --------------------------------------------------------------------------
# Typed events - the vocabulary, so callers cannot invent unsafe payloads
# --------------------------------------------------------------------------


def record_scan(
    log: AuditLog,
    *,
    request_id: str,
    profile: str,
    policy_version: int,
    findings,
    prompt_fingerprint: str,
    blocked: bool,
    level: str = "standard",
    profile_fingerprint: str | None = None,
    decision_tier: str | None = None,
    decision_reasons=None,
) -> AuditEntry:
    """Log what a scan decided, carrying references rather than values.

    Note what is absent: the prompt, the matched text, the mapping. A finding
    contributes its category, its action, its confidence and its record
    reference - enough to reconstruct the decision, useless to an attacker.

    `level` is the profile's `audit_level` (phase 2.4), and it changes how much
    DECISION detail is kept - never how much CONTENT. That distinction is the
    whole design: "full" adds the policy fingerprint the decision was made
    under, the tier it resolved to, the reasons behind it, and each finding's
    span. It adds no prompt, no value, no mapping, because there is no audit
    level at which those become acceptable to store.

    `decision-support` asks for "full" because a decision about a person has to
    be reconstructable years later; the EU jurisdiction floor forces it on
    every profile, which is what makes that clamp visible rather than notional.
    """
    payload = {
        "request_id": request_id,
        "profile": profile,
        "policy_version": policy_version,
        "prompt_fingerprint": prompt_fingerprint,
        "blocked": blocked,
        "audit_level": level,
        "findings": [
            {
                "kind": f.kind,
                "category": f.category,
                "action": f.action,
                "confidence": f.confidence,
                "record_ref": f.record_ref,
                "placeholder": f.placeholder,
                **({"span": list(f.span)} if level == "full" and f.span else {}),
            }
            for f in findings
        ],
    }
    if level == "full":
        # More about the DECISION, still nothing about the content.
        payload["profile_fingerprint"] = profile_fingerprint
        payload["decision_tier"] = decision_tier
        payload["decision_reasons"] = list(decision_reasons or [])
    return log.append("scan", **payload)


def record_policy_change(
    log: AuditLog, *, previous, current, actor: str = "control-plane"
) -> AuditEntry:
    """Log a policy publish, with the diff that caused the behaviour change.

    This is what makes "we act, not just watch" auditable: demo step 7
    changes a policy live, and the reason the next request behaved
    differently is a readable diff rather than a mystery.
    """
    changes: dict[str, dict] = {}
    for name, profile in current.profiles.items():
        before = previous.profiles.get(name) if previous else None
        if before is None:
            changes[name] = {"added": profile.fingerprint}
        elif before.fingerprint != profile.fingerprint:
            changes[name] = {
                str(k): [str(v[0]), str(v[1])] for k, v in profile.diff(before).items()
            }
    for name in (previous.profiles if previous else {}):
        if name not in current.profiles:
            changes[name] = {"removed": True}

    return log.append(
        "policy_change",
        actor=actor,
        from_version=previous.version if previous else None,
        to_version=current.version,
        fingerprints=current.fingerprints,
        changes=changes,
    )


def attach_to_store(log: AuditLog, store) -> None:
    """Make every policy publish write itself to the log, automatically."""
    store.on_publish(lambda prev, cur: record_policy_change(log, previous=prev, current=cur))
