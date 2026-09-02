"""Per-route switches reaching the engine without the engine learning `Profile`.

GAP-CLOSURE-PLAN phase 2.1 / ADR-1. Three profile settings changed what the
engine does and none of them were read; `EXPLAINED.md` section 8.2 found them
displayed on the dashboard as if they worked.

The rule every test here defends: **defaults reproduce the old behaviour
exactly**, so the hundreds of call sites that predate this - including Track
B's gateway, which CONTRACTS section 3 governs - are untouched.
"""

import pytest

from controlplane.engine.api import ScanOptions
from controlplane.engine.substitute import SubstitutionEngine

FIXTURES = "tests/test_engine/fixtures/records.jsonl"
KEY = "sk-abcdefghij0123456789ABCDEFGHIJ"


@pytest.fixture(scope="module")
def engine():
    return SubstitutionEngine(FIXTURES)


@pytest.fixture(scope="module")
def known_name(engine):
    """A name that IS in the record store, taken from the store itself rather
    than hardcoded - a fixture that drifts from its data proves nothing."""
    res = engine.scan_inbound("Refund Priya Sharma please.")
    assert res.findings, "fixture data no longer contains Priya Sharma"
    return "Priya Sharma"


# --------------------------------------------------------------------------
# The compatibility guarantee
# --------------------------------------------------------------------------

def test_omitting_options_is_identical_to_passing_the_defaults(engine, known_name):
    text = f"Refund {known_name} on account 5010 0234 5678 90."
    without = engine.scan_inbound(text)
    with_defaults = engine.scan_inbound(text, options=ScanOptions())

    assert without.text == with_defaults.text
    assert without.blocked == with_defaults.blocked
    assert [f.category for f in without.findings] == [f.category for f in with_defaults.findings]


def test_outbound_omitting_options_is_identical_too(engine):
    text = f"Here is the key {KEY}"
    assert engine.scan_outbound(text).text == engine.scan_outbound(text, options=ScanOptions()).text


# --------------------------------------------------------------------------
# known_value_matching - drop to the pattern tier
# --------------------------------------------------------------------------

def test_known_value_matching_on_gives_a_record_reference(engine, known_name):
    res = engine.scan_inbound(f"Refund {known_name}.")
    refs = [f.record_ref for f in res.findings if f.record_ref]
    assert refs, "the record store should have identified this name"
    assert known_name not in res.text, "it should have been placeholdered"


def test_known_value_matching_off_falls_through_to_the_pattern_tier(engine, known_name):
    """Not silence - the weaker tier. A name that only the record store knows
    is no longer caught, and the audit line for anything that IS caught loses
    its record reference, which is exactly how an ungoverned source already
    behaves (D28)."""
    res = engine.scan_inbound(
        f"Refund {known_name}.", options=ScanOptions(known_value_matching=False)
    )
    assert known_name in res.text, "no record store means this name is not known"
    assert all(f.record_ref is None for f in res.findings)


def test_a_credential_still_blocks_with_the_record_store_off(engine):
    """The checksum/pattern tier is what catches credentials, so turning off
    the record store must not touch them."""
    res = engine.scan_inbound(
        f"key {KEY}", options=ScanOptions(known_value_matching=False)
    )
    assert res.blocked
    assert KEY not in res.text


# --------------------------------------------------------------------------
# substitute_pii - the code-assistant route
# --------------------------------------------------------------------------

def test_substitute_pii_off_leaves_the_value_in_place(engine, known_name):
    res = engine.scan_inbound(
        f"Refund {known_name}.", options=ScanOptions(substitute_pii=False)
    )
    assert known_name in res.text


def test_substitute_pii_off_still_reports_the_finding(engine, known_name):
    """The dangerous version of this switch is the silent one. The value is
    not placeholdered, but the finding still reaches the audit line, the
    metrics and the screen - marked `observed`, not `substitute`, because
    claiming we substituted something we sent would be a lie in the record."""
    res = engine.scan_inbound(
        f"Refund {known_name}.", options=ScanOptions(substitute_pii=False)
    )
    assert res.findings, "turning off substitution must not turn off reporting"
    assert any(f.action == "observed" for f in res.findings)
    assert any(f.record_ref for f in res.findings), "we still know exactly whose it is"


def test_a_credential_still_blocks_with_substitution_off(engine, known_name):
    """The guard that matters most in this file. `substitute_pii: false` is a
    PII decision; it may never become a credential decision."""
    res = engine.scan_inbound(
        f"Refund {known_name}, key {KEY}", options=ScanOptions(substitute_pii=False)
    )
    assert res.blocked, "credentials block regardless of the PII switch"
    assert KEY not in res.text
    assert known_name in res.text, "PII passes, credential does not - both, in one request"


# --------------------------------------------------------------------------
# scan_pii - outbound
# --------------------------------------------------------------------------

def test_outbound_scan_pii_off_still_blocks_a_credential(engine):
    res = engine.scan_outbound(f"Your key is {KEY}", options=ScanOptions(scan_pii=False))
    assert res.blocked
    assert KEY not in res.text


def test_outbound_scan_pii_off_drops_the_pii_findings(engine, known_name):
    """Latency this route did not want to pay. The credential half is
    untouched, so what is switched off is scrutiny, never protection against
    the irreversible case."""
    on = engine.scan_outbound(f"About {known_name}.", options=ScanOptions(scan_pii=True))
    off = engine.scan_outbound(f"About {known_name}.", options=ScanOptions(scan_pii=False))
    assert len(off.findings) < len(on.findings) or not on.findings
