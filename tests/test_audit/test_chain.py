"""Hash-chained audit log.

IDEATION section 18. The demoable property is that editing one row breaks
verification on stage (demo step 8, now Q&A material after the D22 cut). The
non-negotiable property is that a raw sensitive value can never get in here -
otherwise the compliance tool becomes the largest concentration of leaked
data in the company.
"""

from pathlib import Path

import pytest

from controlplane.audit.chain import (
    GENESIS,
    AuditIntegrityError,
    AuditLog,
    record_scan,
    text_fingerprint,
)
from controlplane.engine.substitute import SubstitutionEngine

FIXTURE = str(Path(__file__).parents[1] / "test_engine" / "fixtures" / "records.jsonl")


@pytest.fixture()
def log() -> AuditLog:
    return AuditLog()


@pytest.fixture(scope="module")
def engine() -> SubstitutionEngine:
    return SubstitutionEngine(FIXTURE)


# --------------------------------------------------------------------------
# The chain
# --------------------------------------------------------------------------

def test_empty_log_verifies(log):
    assert log.verify()
    assert log.head == GENESIS


def test_entries_chain_to_their_predecessor(log):
    a = log.append("scan", request_id="r1")
    b = log.append("scan", request_id="r2")
    assert a.prev_hash == GENESIS
    assert b.prev_hash == a.entry_hash
    assert log.verify()


def test_a_long_chain_verifies(log):
    for i in range(200):
        log.append("scan", request_id=f"r{i}")
    result = log.verify()
    assert result.ok and result.entries == 200


# --------------------------------------------------------------------------
# Tamper evidence - the thing we demo
# --------------------------------------------------------------------------

def test_editing_a_record_breaks_verification(log):
    """Demo step 8: edit one row live, watch verification fail."""
    for i in range(5):
        log.append("scan", request_id=f"r{i}", blocked=False)

    assert log.verify()
    log._tamper(2, payload={"request_id": "r2", "blocked": True})

    result = log.verify()
    assert not result.ok
    assert result.broken_at == 2
    assert "altered" in result.reason


def test_tampering_breaks_every_hash_after_it(log):
    """Not just the edited row - the whole tail. That is the point of a chain."""
    for i in range(5):
        log.append("scan", request_id=f"r{i}")
    log._tamper(1, event="nothing_to_see_here")

    assert log.verify().broken_at == 1


def test_tampering_with_the_first_record_is_caught(log):
    log.append("scan", request_id="r0")
    log.append("scan", request_id="r1")
    log._tamper(0, payload={"request_id": "tampered"})
    assert not log.verify()


def test_reordering_is_caught(log):
    log.append("scan", request_id="r0")
    log.append("scan", request_id="r1")
    log._entries.reverse()
    result = log.verify()
    assert not result.ok


# --------------------------------------------------------------------------
# What must never get in
# --------------------------------------------------------------------------

@pytest.mark.parametrize(
    "payload",
    [
        {"prompt": "my key is sk-abcdefghij0123456789ABCDEFGHIJ"},
        {"note": "AKIAIOSFODNN7EXAMPLE"},
        {"token": "ghp_" + "a" * 36},
        {"account": "50100234567890"},
        {"nested": {"deeper": {"card": "4539578763621486"}}},
        {"header": "-----BEGIN RSA PRIVATE KEY-----"},
    ],
)
def test_sensitive_payloads_are_refused(log, payload):
    """Enforced, not left to caller discipline.

    A convention nobody enforces is a convention that gets broken at 2am
    before a demo. Failing the write is correct: a compliance log that
    quietly stores a secret is worse than one that errors.
    """
    with pytest.raises(AuditIntegrityError):
        log.append("scan", **payload)
    assert len(log) == 0, "refused entry must not be committed"


def test_record_references_are_allowed(log):
    """"matched customer record 44219" is the audit line we want.

    A reference points into a system that already holds the data under its
    own controls, which is exactly why it is safe to write down.
    """
    entry = log.append("scan", record_ref="customer:44219", category="customer_name")
    assert entry.payload["record_ref"] == "customer:44219"


def test_fingerprint_proves_content_without_keeping_it(log):
    prompt = "Draft a refund email to Priya Sharma."
    log.append("scan", prompt_fingerprint=text_fingerprint(prompt))

    assert "Priya" not in log.export()
    # an auditor supplies the text and we confirm the match
    assert log.entries[0].payload["prompt_fingerprint"] == text_fingerprint(prompt)
    assert log.entries[0].payload["prompt_fingerprint"] != text_fingerprint(prompt + "!")


# --------------------------------------------------------------------------
# The integration that matters: engine findings -> audit line
# --------------------------------------------------------------------------

def test_scan_findings_log_without_leaking(log, engine):
    """The full path: a real prompt, a real finding, and nothing recoverable."""
    prompt = "Refund Priya Sharma on account 50100234567890."
    scanned = engine.scan_inbound(prompt)

    record_scan(
        log,
        request_id="req-1",
        profile="internal-knowledge",
        policy_version=1,
        findings=scanned.findings,
        prompt_fingerprint=text_fingerprint(prompt),
        blocked=scanned.blocked,
    )

    dump = log.export()
    assert "customer:44219" in dump          # the reference survives
    for secret in ("Priya", "Sharma", "50100234567890"):
        assert secret not in dump            # the value does not
    assert log.verify()


def test_blocked_credential_is_logged_by_category_only(log, engine):
    scanned = engine.scan_inbound("key sk-abcdefghij0123456789ABCDEFGHIJ here")
    record_scan(
        log,
        request_id="req-2",
        profile="internal-knowledge",
        policy_version=1,
        findings=scanned.findings,
        prompt_fingerprint=text_fingerprint("redacted"),
        blocked=scanned.blocked,
    )
    dump = log.export()
    assert "api_key" in dump and "sk-abcdefghij" not in dump


# --------------------------------------------------------------------------
# Housekeeping
# --------------------------------------------------------------------------

def test_by_event_filters(log):
    log.append("scan", request_id="r0")
    log.append("policy_change", actor="me")
    assert len(log.by_event("scan")) == 1
    assert len(log.by_event("policy_change")) == 1


def test_entries_are_a_copy_not_the_live_list(log):
    log.append("scan", request_id="r0")
    log.entries.clear()
    assert len(log) == 1


def test_export_is_one_json_object_per_line(log):
    log.append("scan", request_id="r0")
    log.append("scan", request_id="r1")
    assert len(log.export().splitlines()) == 2


# --------------------------------------------------------------------------
# audit_level (phase 2.4) - more DECISION detail, never more CONTENT
# --------------------------------------------------------------------------

class _F:
    """A finding, shaped as the engine emits one."""
    def __init__(self, category="customer_name", ref="customer:44219", span=(7, 19)):
        self.kind, self.category, self.action = "known_value", category, "substitute"
        self.confidence, self.record_ref, self.placeholder = 1.0, ref, "[[CUST_A]]"
        self.span = span


def _entry(level, **kw):
    log = AuditLog()
    return record_scan(
        log,
        request_id="req_1",
        profile="p",
        policy_version=1,
        findings=[_F()],
        prompt_fingerprint="abc123",
        blocked=False,
        level=level,
        **kw,
    )


def test_standard_is_what_it_always_was():
    payload = _entry("standard").payload
    assert payload["audit_level"] == "standard"
    assert "profile_fingerprint" not in payload
    assert "decision_tier" not in payload
    assert "span" not in payload["findings"][0]


def test_full_adds_the_context_a_decision_has_to_be_reconstructable_from():
    payload = _entry(
        "full",
        profile_fingerprint="fp123",
        decision_tier="review",
        decision_reasons=["profile reviews every response"],
    ).payload
    assert payload["profile_fingerprint"] == "fp123"
    assert payload["decision_tier"] == "review"
    assert payload["decision_reasons"] == ["profile reviews every response"]
    assert payload["findings"][0]["span"] == [7, 19]


def test_neither_level_ever_carries_content():
    """The test that would have caught a regression here at any point in this
    project. `full` means more about the decision - it has never meant, and
    must never mean, more about what the customer said."""
    for level in ("standard", "full"):
        blob = repr(_entry(
            level,
            profile_fingerprint="fp",
            decision_tier="allow",
            decision_reasons=["mitigated by substitution"],
        ).payload)
        for secret in ("Priya", "Sharma", "45230", "priya.sharma@example.com"):
            assert secret not in blob, f"{level} leaked {secret!r}"


def test_an_unknown_level_degrades_to_standard_rather_than_crashing():
    """A profile compiled by a newer version, read by an older one. Failing
    open on VOLUME of detail is safe; failing closed would lose the entry."""
    payload = _entry("something-new").payload
    assert "profile_fingerprint" not in payload
    assert payload["findings"], "the entry itself must still be written"
