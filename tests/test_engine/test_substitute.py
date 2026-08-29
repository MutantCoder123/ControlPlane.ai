"""End-to-end tests for the substitution engine.

These are the claims the pitch actually makes. If any of them go red, the
demo is wrong on stage rather than merely incomplete.
"""

from pathlib import Path

import pytest

from controlplane.engine.api import EngineConfig
from controlplane.engine.substitute import SubstitutionEngine

FIXTURE = str(Path(__file__).parent / "fixtures" / "records.jsonl")


@pytest.fixture(scope="module")
def engine() -> SubstitutionEngine:
    return SubstitutionEngine(FIXTURE)


# --------------------------------------------------------------------------
# THE claim: the provider never sees real personal data
# --------------------------------------------------------------------------

def test_provider_never_sees_the_real_name(engine):
    result = engine.scan_inbound("Draft a refund email to Priya Sharma.")
    assert "Priya" not in result.text
    assert "Sharma" not in result.text
    assert result.findings[0].record_ref == "customer:44219"


def test_round_trip_returns_the_real_answer(engine):
    """Demo step 3, in one test.

    Paste a real record, get a correct and useful answer back, and the model
    only ever saw a placeholder.
    """
    prompt = "Draft a refund email to Priya Sharma at priya.sharma@example.com."
    scanned = engine.scan_inbound(prompt)

    # what the provider actually received
    assert "Priya Sharma" not in scanned.text
    assert "priya.sharma@example.com" not in scanned.text

    # the model answers about placeholders quite happily
    name_ph = next(f.placeholder for f in scanned.findings if f.category == "customer_name")
    model_reply = f"Dear {name_ph}, your refund is on its way."
    restored = engine.restore(model_reply, scanned.mapping)

    assert "Priya Sharma" in restored.text
    assert restored.unrestored == []


def test_mapping_is_in_text_order(engine):
    """`next(iter(mapping))` should be the FIRST entity in the prompt.

    Replacement runs right to left so spans stay valid, which left the
    mapping reversed. A consumer indexing it positionally would silently get
    the wrong entity - the sort of thing that shows up as a baffling demo
    rather than a crash.
    """
    scanned = engine.scan_inbound("Contact Priya Sharma, then Rajesh Kumar.")
    first = next(iter(scanned.mapping))
    assert scanned.mapping[first] == "Priya Sharma"


def test_same_entity_gets_the_same_placeholder(engine):
    """Relational reasoning has to survive substitution."""
    result = engine.scan_inbound(
        "Priya Sharma called. Priya Sharma is upset. Email Priya Sharma today."
    )
    placeholders = {f.placeholder for f in result.findings if f.placeholder}
    assert len(placeholders) == 1
    assert result.text.count(placeholders.pop()) == 3


def test_distinct_entities_get_distinct_placeholders(engine):
    result = engine.scan_inbound("Transfer from Priya Sharma to Rajesh Kumar.")
    placeholders = {f.placeholder for f in result.findings if f.placeholder}
    assert len(placeholders) == 2


def test_mapping_is_request_scoped_not_shared(engine):
    """Statelessness (IDEATION section 3): nothing carries between requests."""
    a = engine.scan_inbound("Priya Sharma")
    b = engine.scan_inbound("Rajesh Kumar")
    assert set(a.mapping) & set(b.mapping) == set() or a.mapping != b.mapping
    assert "Priya Sharma" not in b.mapping.values()


def test_clean_prompt_is_untouched(engine):
    prompt = "Summarise last quarter's support tickets."
    result = engine.scan_inbound(prompt)
    assert result.text == prompt
    assert result.findings == [] and result.mapping == {} and not result.blocked


# --------------------------------------------------------------------------
# D16 - break the linkage, preserve the arithmetic
# --------------------------------------------------------------------------

def test_operands_pass_through_untouched(engine):
    """The number is not the sensitive part; the link to the name is."""
    result = engine.scan_inbound("Priya Sharma has a balance of 45230 rupees.")
    assert "45230" in result.text
    assert "Priya" not in result.text


def test_arithmetic_survives_substitution(engine):
    """A sum computed over substituted text is still the right sum."""
    prompt = "Add the balances for Priya Sharma (45230) and Rajesh Kumar (12750)."
    scanned = engine.scan_inbound(prompt)

    assert "45230" in scanned.text and "12750" in scanned.text

    model_reply = "The combined balance is 57980."
    restored = engine.restore(model_reply, scanned.mapping)
    assert "57980" in restored.text
    assert 45230 + 12750 == 57980


def test_salary_operand_is_not_substituted(engine):
    result = engine.scan_inbound("Anita Desai earns 98000 per year.")
    assert "98000" in result.text
    assert "Anita" not in result.text


# --------------------------------------------------------------------------
# Block vs substitute (IDEATION section 9.5)
# --------------------------------------------------------------------------

def test_credential_blocks_the_request(engine):
    result = engine.scan_inbound("Use key sk-abcdefghij0123456789ABCDEFGHIJ to call it.")
    assert result.blocked
    assert "sk-abcdefghij0123456789ABCDEFGHIJ" not in result.text
    assert result.block_reason and "api_key" in result.block_reason


def test_blocked_credential_is_not_in_the_mapping(engine):
    """We are not sending it, so there is nothing to restore."""
    result = engine.scan_inbound("token ghp_" + "a" * 36)
    assert result.blocked
    assert result.mapping == {}


def test_customer_data_substitutes_rather_than_blocks(engine):
    """Blocking every prompt with customer data blocks the use case."""
    result = engine.scan_inbound("Refund Priya Sharma please.")
    assert not result.blocked
    assert result.findings[0].action == "substitute"


# --------------------------------------------------------------------------
# The tiers, and which one wins
# --------------------------------------------------------------------------

def test_known_value_beats_pattern_on_the_same_span(engine):
    """"matched customer record 44219" beats "looks like a card number"."""
    result = engine.scan_inbound("Account 50100234567890 needs review.")
    assert len(result.findings) == 1
    assert result.findings[0].kind == "known_value"
    assert result.findings[0].record_ref == "customer:44219"
    assert result.findings[0].confidence == 1.0


def test_published_test_card_does_not_fire(engine):
    """IDEATION section 9.2's headline claim, end to end."""
    prompt = "Try 4111 1111 1111 1111 in staging."
    result = engine.scan_inbound(prompt)
    assert result.findings == []
    assert result.text == prompt


def test_ungoverned_record_still_gets_pattern_cover(engine):
    """D28 - the floor under the half with no classification to inherit.

    Meera Nair is not in the known-value store, so her name goes through
    untouched. Her card still gets caught by the checksum tier - with no
    record_ref, because we genuinely do not know whose card it is.
    """
    result = engine.scan_inbound("Meera Nair paid with 4539578763621486.")
    assert "Meera Nair" in result.text          # no classification to inherit
    assert "4539578763621486" not in result.text  # but the floor still holds

    card = [f for f in result.findings if f.category == "payment_card"]
    assert len(card) == 1
    assert card[0].kind == "pattern"
    assert card[0].record_ref is None
    assert card[0].confidence < 1.0


# --------------------------------------------------------------------------
# Restoration - D15, the one that fails on stage
# --------------------------------------------------------------------------

def test_restore_survives_a_possessive(engine):
    scanned = engine.scan_inbound("Priya Sharma")
    ph = next(iter(scanned.mapping))
    restored = engine.restore(f"{ph}'s balance is 45230.", scanned.mapping)
    assert restored.text == "Priya Sharma's balance is 45230."
    assert restored.unrestored == []


@pytest.mark.parametrize(
    "template",
    [
        "{p} called today.",
        "{p}'s account is fine.",
        "Please contact {p}.",
        "```\ncustomer = \"{p}\"\n```",
        '{{"customer": "{p}"}}',
        "Contact ({p}) now.",
        "See `{p}` above.",
    ],
)
def test_restore_survives_model_formatting(engine, template):
    scanned = engine.scan_inbound("Priya Sharma")
    ph = next(iter(scanned.mapping))
    restored = engine.restore(template.format(p=ph), scanned.mapping)
    assert "Priya Sharma" in restored.text
    assert restored.unrestored == []
    assert "[[" not in restored.text


def test_restore_flags_a_placeholder_it_cannot_resolve(engine):
    """The D15 alarm. A model that invents a token must not fail silently."""
    restored = engine.restore("Hello [[CUST_Z]] and welcome.", {"[[CUST_A]]": "Priya Sharma"})
    assert restored.unrestored == ["[[CUST_Z]]"]


def test_restore_with_empty_mapping_still_reports_leftovers(engine):
    assert engine.restore("Hi [[CUST_A]]", {}).unrestored == ["[[CUST_A]]"]


def test_restore_counts_every_occurrence(engine):
    scanned = engine.scan_inbound("Priya Sharma")
    ph = next(iter(scanned.mapping))
    restored = engine.restore(f"{ph} {ph} {ph}", scanned.mapping)
    assert restored.restored == 3


def test_restore_handles_a_value_containing_backslashes(engine):
    """A real value must never be re-interpreted as a regex replacement."""
    restored = engine.restore("[[CUST_A]] here", {"[[CUST_A]]": r"Back\slash"})
    assert restored.text == r"Back\slash here"


# --------------------------------------------------------------------------
# Outbound (IDEATION section 9.6)
# --------------------------------------------------------------------------

def test_outbound_blocks_a_credential(engine):
    """Demo step 2: the model tries to emit a live key."""
    result = engine.scan_outbound("Sure, the key is AKIAIOSFODNN7EXAMPLE.")
    assert result.blocked
    assert "AKIAIOSFODNN7EXAMPLE" not in result.text


def test_outbound_leaves_ordinary_text_alone(engine):
    text = "Your refund has been processed."
    result = engine.scan_outbound(text)
    assert result.text == text and not result.blocked


# --------------------------------------------------------------------------
# Fail closed (IDEATION section 17)
# --------------------------------------------------------------------------

@pytest.mark.parametrize("bad", [None, 42, b"bytes", ["list"]])
def test_non_text_input_blocks_rather_than_raising(engine, bad):
    """The gateway is on the request path and must be able to trust us."""
    result = engine.scan_inbound(bad)
    assert result.blocked
    assert result.text == ""


def test_empty_prompt_is_allowed(engine):
    result = engine.scan_inbound("")
    assert not result.blocked and result.text == ""


def test_engine_accepts_a_config(engine):
    e = SubstitutionEngine(FIXTURE, EngineConfig(bloom_capacity=10, bloom_error_rate=0.05))
    assert e.scan_inbound("Priya Sharma").findings


# --------------------------------------------------------------------------
# Never hold or leak a raw value
# --------------------------------------------------------------------------

def test_findings_carry_no_raw_values(engine):
    """Findings go into the audit log, which must never hold the value."""
    result = engine.scan_inbound("Priya Sharma, account 50100234567890.")
    blob = repr(result.findings)
    assert "Priya" not in blob
    assert "50100234567890" not in blob
