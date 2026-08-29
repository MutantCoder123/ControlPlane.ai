"""Known-value store tests.

The claims under test are the ones the pitch rests on (IDEATION section 9.2):
we match OUR data deterministically, we carry a record reference into the
audit line, we never hold a raw value, and we skip the ungoverned half on
purpose rather than by accident (D28).
"""

from pathlib import Path

import pytest

from controlplane.engine.knownvalue import (
    KnownValueStore,
    digits_key,
    normalise,
)

FIXTURE = Path(__file__).parent / "fixtures" / "records.jsonl"


@pytest.fixture(scope="module")
def store() -> KnownValueStore:
    return KnownValueStore.from_jsonl(FIXTURE)


# --------------------------------------------------------------------------
# Normalisation - what D9 does and does not buy us
# --------------------------------------------------------------------------

@pytest.mark.parametrize(
    "raw,expected",
    [
        ("Priya Sharma", "priya sharma"),
        ("  Priya   Sharma  ", "priya sharma"),
        ("PRIYA SHARMA", "priya sharma"),
        ('"Priya Sharma".', "priya sharma"),
        ("priya.sharma@example.com", "priya.sharma@example.com"),
    ],
)
def test_normalise(raw, expected):
    assert normalise(raw) == expected


def test_normalise_is_unicode_stable():
    """Composed vs decomposed accents must hash the same."""
    assert normalise("André") == normalise("André")


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("50100234567890", "50100234567890"),
        ("5010 0234 5678 90", "50100234567890"),
        ("5010-0234-5678-90", "50100234567890"),
        ("Priya Sharma", None),      # not numeric - must not collapse
        ("12345", None),             # too short to be an identifier
        ("E-3311", None),            # has letters
    ],
)
def test_digits_key(raw, expected):
    assert digits_key(raw) == expected


# --------------------------------------------------------------------------
# The core claim: we match our own data, with a record reference
# --------------------------------------------------------------------------

def test_matches_a_known_customer_name(store):
    match = store.lookup("Priya Sharma")
    assert match is not None
    assert match.record_ref == "customer:44219"
    assert match.category == "customer_name"
    assert match.role == "identifier"


def test_audit_reference_not_just_a_pattern_name(store):
    """'matched customer record 44219' beats 'matched a regex'."""
    assert store.lookup("priya.sharma@example.com").record_ref == "customer:44219"
    assert store.lookup("50100234567890").record_ref == "customer:44219"


def test_case_and_punctuation_insensitive(store):
    assert store.lookup("PRIYA SHARMA") is not None
    assert store.lookup("  priya   sharma  ") is not None


def test_account_number_with_separators(store):
    """A human pastes the account number however their screen showed it."""
    assert store.lookup("5010 0234 5678 90").record_ref == "customer:44219"


@pytest.mark.parametrize(
    "rendering",
    [
        "50100234567890",
        "5010 0234 5678 90",
        "5010-0234-5678-90",
        "5010 0234 567890",
    ],
)
def test_scan_finds_a_grouped_account_number(store, rendering):
    """Regression: lookup() handled separators but scan() never built the window.

    n-gram width was set by the longest NAME in the store - two tokens - so a
    four-token account number could not be assembled and sailed through
    untouched. The unit test passed because it called lookup() with the whole
    string; only an end-to-end prompt showed the hole.
    """
    text = f"Please check account {rendering} today."
    hits = store.scan(text)
    assert [h.match.record_ref for h in hits] == ["customer:44219"]
    assert text[slice(*hits[0].span)] == rendering


def test_numeric_widening_does_not_join_unrelated_numbers(store):
    """Widening the window must not glue two adjacent amounts into one hit.

    45230 and 12750 are both real values (two customers' balances), so they
    SHOULD be found individually - as operands, which substitute.py then
    leaves alone. What must not happen is "45230 12750" being read as a
    single fourteen-digit identifier.
    """
    hits = store.scan("Totals were 45230 12750 last quarter.")
    assert [h.text for h in hits] == ["45230", "12750"]
    assert all(h.match.role == "operand" for h in hits)


def test_unknown_grouped_number_is_not_invented(store):
    """Widening must not manufacture a match out of unrelated digits."""
    assert store.scan("Ref 1234 5678 9012 34 is not ours.") == []


def test_unknown_value_does_not_match(store):
    assert store.lookup("Somebody Else") is None
    assert store.lookup("") is None


def test_operands_are_indexed_with_their_role(store):
    """We index operands so the engine can DECIDE not to substitute them.

    Absence would achieve the same outcome, but then the code would contain
    no evidence of the decision. D16 is a choice, so it should be visible.
    """
    match = store.lookup("45230")
    assert match is not None and match.role == "operand"


# --------------------------------------------------------------------------
# D28 - the ungoverned half
# --------------------------------------------------------------------------

def test_ungoverned_records_are_not_indexed(store):
    """Meera Nair is real, but her record carries no classification.

    She must fall through to the pattern tier. This is the graceful
    degradation the Round 2 brief's "mix of well- and loosely-governed
    sources" actually demands.
    """
    assert store.lookup("Meera Nair") is None
    assert store.lookup("Arjun Menon") is None


def test_ungoverned_skips_are_counted_not_silent(store):
    assert store.skipped_ungoverned == 2
    assert store.record_count == 4


# --------------------------------------------------------------------------
# Never hold a raw value
# --------------------------------------------------------------------------

def test_no_raw_values_in_repr(store):
    assert "Priya" not in repr(store)
    assert "50100234567890" not in repr(store)


def test_no_raw_values_anywhere_in_state(store):
    """Walk the object's own state and assert the values are simply absent."""
    blob = repr(store.__dict__)
    for secret in ("Priya", "Sharma", "50100234567890", "example.com"):
        assert secret not in blob, f"{secret!r} is recoverable from store state"


# --------------------------------------------------------------------------
# Scanning text
# --------------------------------------------------------------------------

def test_scan_finds_value_in_a_sentence(store):
    text = "Please refund Priya Sharma for order 88."
    hits = store.scan(text)
    assert len(hits) == 1
    assert hits[0].text == "Priya Sharma"
    assert text[slice(*hits[0].span)] == "Priya Sharma"


def test_scan_spans_index_the_original_text(store):
    text = 'Customer "Priya Sharma", account 50100234567890.'
    for hit in store.scan(text):
        assert text[slice(*hit.span)] == hit.text


def test_longest_match_wins(store):
    """'Priya Sharma' must not also yield a separate 'Priya'.

    One entity has to map to one placeholder or the model loses the thread.
    """
    hits = store.scan("Priya Sharma called about her account.")
    assert [h.text for h in hits] == ["Priya Sharma"]


def test_scan_finds_multiple_distinct_entities(store):
    text = "Transfer from Priya Sharma to Rajesh Kumar."
    refs = {h.match.record_ref for h in store.scan(text)}
    assert refs == {"customer:44219", "customer:44220"}


def test_scan_clean_text_is_empty(store):
    assert store.scan("What is the weather in Bengaluru today?") == []


def test_scan_handles_trailing_punctuation(store):
    hits = store.scan("The customer is Priya Sharma.")
    assert hits and hits[0].text == "Priya Sharma"


@pytest.mark.parametrize(
    "text",
    [
        "Send it to Priya. Sharma is a common surname.",
        "Ask Priya, Sharma will confirm.",
        "Priya; Sharma is elsewhere.",
    ],
)
def test_scan_does_not_match_across_punctuation(store, text):
    """Two tokens separated by punctuation are two things, not one entity.

    Regression: edge punctuation is stripped before n-grams are joined, so
    "Priya. Sharma" looked exactly like "Priya Sharma" to the matcher.
    Substituting it would have swallowed the sentence boundary and changed
    the meaning of the sentence - a correctness bug and a false positive in
    the same match.
    """
    hits = store.scan(text)
    assert hits == [], f"matched across punctuation: {[h.text for h in hits]}"


def test_scan_still_matches_across_a_newline(store):
    """A wrapped line is still one name - only punctuation ends a run."""
    hits = store.scan("Please refund Priya\nSharma today.")
    assert [h.match.record_ref for h in hits] == ["customer:44219"]
