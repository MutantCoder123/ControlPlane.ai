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


def test_round_trip_against_a_reply_not_derived_from_the_scan(engine):
    """The same claim as the test above, but this one can actually fail.

    Track B pointed out that a round-trip test which builds the model reply
    out of the placeholders it just received passes by construction - it
    proves `restore` can undo something we handed it, not that the round trip
    survives a reply we did not write.

    So: pin what the provider saw, then hand-write the reply the way a model
    actually answers - possessive, reordered, one placeholder used twice. If
    the placeholder format changes, the first assertion fails loudly, which is
    correct: the format is a contract surface (CONTRACTS section 4).
    """
    prompt = "Draft a refund email to Priya Sharma at priya.sharma@example.com."
    scanned = engine.scan_inbound(prompt)

    assert scanned.text == "Draft a refund email to [[CUST_A]] at [[EMAIL_A]]."

    model_reply = (
        "Hi [[CUST_A]], I have emailed confirmation to [[EMAIL_A]]. "
        "[[CUST_A]]'s refund of 45230 clears in 3 days."
    )
    restored = engine.restore(model_reply, scanned.mapping)

    assert restored.text == (
        "Hi Priya Sharma, I have emailed confirmation to "
        "priya.sharma@example.com. Priya Sharma's refund of 45230 clears in 3 days."
    )
    assert restored.unrestored == []


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


# --------------------------------------------------------------------------
# Request scope - placeholder identity across the scans of one request
# --------------------------------------------------------------------------

def test_without_a_scope_two_customers_collide(engine):
    """The bug Track B found at the seam, pinned so it cannot come back.

    A request is rarely one piece of text - system prompt, several messages,
    sometimes several content parts each - and every one gets scanned
    separately. Per-call numbering meant two different customers in one
    request both became [[CUST_A]]: the provider is told they are the same
    person, and the merged mapping restores the wrong name.
    """
    a = engine.scan_inbound("First: Priya Sharma.")
    b = engine.scan_inbound("Second: Rajesh Kumar.")
    assert a.text == b.text.replace("Second", "First")   # both [[CUST_A]]

    merged = {**a.mapping, **b.mapping}
    assert engine.restore(a.text, merged).text == "First: Rajesh Kumar."
    #                                                     ^ the wrong customer


def test_a_scope_keeps_two_customers_distinct(engine):
    scope = engine.new_request_scope()
    a = engine.scan_inbound("First: Priya Sharma.", scope=scope)
    b = engine.scan_inbound("Second: Rajesh Kumar.", scope=scope)

    assert a.text != b.text
    assert engine.restore(a.text, scope.mapping).text == "First: Priya Sharma."
    assert engine.restore(b.text, scope.mapping).text == "Second: Rajesh Kumar."


def test_the_same_person_keeps_one_placeholder_across_messages(engine):
    """Identity, not just distinct numbering.

    If Priya is [[CUST_A]] in message 1 and [[CUST_C]] in message 7, the model
    can no longer tell it is one person and relational reasoning breaks across
    the conversation - the same failure the within-call rule exists to prevent.
    """
    scope = engine.new_request_scope()
    first = engine.scan_inbound("Priya Sharma called.", scope=scope)
    engine.scan_inbound("Rajesh Kumar also called.", scope=scope)
    later = engine.scan_inbound("Priya Sharma called back.", scope=scope)

    assert first.text.split()[0] == later.text.split()[0]
    assert len(scope.mapping) == 2


def test_scan_result_mapping_is_cumulative(engine):
    """A caller who naively merges each result gets the right answer too.

    Two obvious usages - merge every ScanResult.mapping, or read scope.mapping
    at the end - must not disagree. Designing so the lazy path is also correct
    is cheaper than documenting the difference.
    """
    scope = engine.new_request_scope()
    engine.scan_inbound("Priya Sharma.", scope=scope)
    second = engine.scan_inbound("Rajesh Kumar.", scope=scope)
    assert second.mapping == scope.mapping


def test_spans_still_index_each_original_text(engine):
    """Why this belongs in the engine rather than a join on the caller's side.

    CONTRACTS section 3 rule 4: spans refer to the ORIGINAL text, because the
    audit entry needs those offsets. Concatenating messages to share numbering
    would make every span point into a joined string that was never sent.
    """
    scope = engine.new_request_scope()
    texts = ["Refund Priya Sharma today.", "Also refund Rajesh Kumar."]
    for text in texts:
        result = engine.scan_inbound(text, scope=scope)
        for finding in result.findings:
            assert text[slice(*finding.span)] in ("Priya Sharma", "Rajesh Kumar")


def test_scope_is_caller_owned_and_the_engine_holds_none(engine):
    """Statelessness (IDEATION section 3) survives the fix.

    The scope is a value the caller passes in and drops. If the engine kept
    scopes of its own, we would have quietly built the per-request memory the
    whole positioning forbids.
    """
    scope = engine.new_request_scope()
    engine.scan_inbound("Priya Sharma.", scope=scope)

    blob = repr(engine.__dict__)
    assert "Priya" not in blob
    assert not any("scope" in k.lower() for k in engine.__dict__)

    fresh = engine.new_request_scope()
    assert fresh.mapping == {} and fresh is not scope


def test_scope_survives_an_empty_and_a_clean_text(engine):
    scope = engine.new_request_scope()
    engine.scan_inbound("Priya Sharma.", scope=scope)
    assert engine.scan_inbound("", scope=scope).mapping == scope.mapping
    assert engine.scan_inbound("Nothing sensitive here.", scope=scope).mapping == scope.mapping
    assert len(scope.mapping) == 1


def test_blocked_scan_does_not_corrupt_the_scope(engine):
    scope = engine.new_request_scope()
    engine.scan_inbound("Priya Sharma.", scope=scope)
    blocked = engine.scan_inbound("key sk-abcdefghij0123456789ABCDEFGHIJ", scope=scope)
    assert blocked.blocked
    assert scope.mapping == {"[[CUST_A]]": "Priya Sharma"}


def test_omitting_the_scope_still_works_for_a_single_text(engine):
    """Backwards compatible - a genuinely single-text request needs no scope."""
    result = engine.scan_inbound("Refund Priya Sharma.")
    assert result.mapping and engine.restore(result.text, result.mapping).unrestored == []
