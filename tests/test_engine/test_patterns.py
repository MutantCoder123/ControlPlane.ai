"""Pattern + checksum tier tests.

The claim under test is IDEATION section 9.1: the checksums are what make
this tier deterministic. Without them every long order number reads as a
card, and false-positive volume is the alert-fatigue failure the Round 2
brief names directly.
"""

import pytest

from controlplane.engine.patterns import (
    KNOWN_TEST_VALUES,
    is_known_test_value,
    luhn_valid,
    mod97_valid,
    scan,
    verhoeff_valid,
)


# --------------------------------------------------------------------------
# Checksums
# --------------------------------------------------------------------------

@pytest.mark.parametrize("digits", ["4539578763621486", "5555555555554444", "378282246310005"])
def test_luhn_accepts_valid(digits):
    assert luhn_valid(digits)


@pytest.mark.parametrize(
    "digits",
    [
        "4539578763621487",   # one digit off
        "1234567890123",      # ordinary long number
        "88001234567890",     # plausible order number
        "",
        "not-a-number",
    ],
)
def test_luhn_rejects_invalid(digits):
    assert not luhn_valid(digits)


def test_luhn_is_why_order_numbers_do_not_fire():
    """The point of the checksum, stated as a test.

    A 14-digit order number is exactly what a naive card regex flags. The
    checksum is the difference between a detector and a nuisance.
    """
    assert not luhn_valid("88001234567890")
    assert scan("Order 88001234567890 shipped today.") == []


@pytest.mark.parametrize("digits", ["234123412346", "999999990019"])
def test_verhoeff_accepts_valid(digits):
    assert verhoeff_valid(digits)


@pytest.mark.parametrize(
    "digits",
    [
        "234123412345",   # wrong check digit
        "123412341234",   # starts with 1 - not a valid Aadhaar
        "01234123412",    # starts with 0, and too short
        "23412341234",    # 11 digits
    ],
)
def test_verhoeff_rejects_invalid(digits):
    assert not verhoeff_valid(digits)


def test_verhoeff_catches_transposition():
    """Why UIDAI chose Verhoeff over Luhn: it catches swapped digits."""
    valid = "234123412346"
    swapped = valid[:4] + valid[5] + valid[4] + valid[6:]
    assert verhoeff_valid(valid)
    assert not verhoeff_valid(swapped)


@pytest.mark.parametrize("iban", ["GB82WEST12345698765432", "DE89370400440532013000"])
def test_mod97_accepts_valid(iban):
    assert mod97_valid(iban)


def test_mod97_rejects_invalid():
    assert not mod97_valid("GB82WEST12345698765433")


# --------------------------------------------------------------------------
# Credentials block
# --------------------------------------------------------------------------

@pytest.mark.parametrize(
    "text,category",
    [
        ("key is sk-abcdefghij0123456789ABCDEFGHIJ here", "api_key"),
        ("sk-ant-api03-aaaaaaaaaaaaaaaaaaaaaaaa", "api_key"),
        ("ghp_" + "a" * 36, "api_key"),
        ("AKIAIOSFODNN7EXAMPLE", "api_key"),
        ("xoxb-1234567890-abcdefghij", "api_key"),
        ("eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.dozjgNryP4J3jVmNHl0w5N_XgL0n3I9PlFUP0THsR8U", "jwt"),
        ("-----BEGIN RSA PRIVATE KEY-----", "private_key"),
    ],
)
def test_credentials_are_blocked_not_substituted(text, category):
    """No legitimate reason to send a key to a model, and refusing is free."""
    hits = scan(text)
    assert hits, f"missed credential in {text!r}"
    assert hits[0].category == category
    assert hits[0].action == "block"


def test_ordinary_text_yields_nothing():
    assert scan("Can you summarise last quarter's support tickets?") == []


# --------------------------------------------------------------------------
# PII substitutes rather than blocking
# --------------------------------------------------------------------------

def test_card_substitutes_rather_than_blocks():
    """Blocking every prompt with customer data blocks the use case."""
    hits = scan("Card on file is 4539578763621486.")
    assert len(hits) == 1
    assert hits[0].category == "payment_card"
    assert hits[0].action == "substitute"


def test_card_with_separators_is_found():
    assert scan("4539 5787 6362 1486") and scan("4539-5787-6362-1486")


def test_aadhaar_is_found():
    hits = scan("Aadhaar 2341 2341 2346 on file.")
    assert len(hits) == 1 and hits[0].category == "aadhaar"


def test_spans_index_the_original_text():
    text = "Card on file is 4539578763621486, thanks."
    for hit in scan(text):
        assert text[slice(*hit.span)] == hit.text


# --------------------------------------------------------------------------
# "Test data stops firing" - IDEATION section 9.2
# --------------------------------------------------------------------------

def test_published_test_card_does_not_fire():
    """The headline claim, made literally true rather than approximately.

    4111 1111 1111 1111 passes Luhn. On shape alone it is indistinguishable
    from a real card, so we suppress the networks' PUBLISHED test numbers
    explicitly - the same principle as the rest of the design: suppress what
    we KNOW is test data, never guess from shape.
    """
    assert luhn_valid("4111111111111111")
    assert scan("Try 4111 1111 1111 1111 in staging.") == []


@pytest.mark.parametrize("card", sorted(KNOWN_TEST_VALUES))
def test_every_published_test_card_is_suppressed(card):
    assert is_known_test_value(card)
    assert scan(f"Use {card} for the test.") == []


def test_a_real_looking_card_still_fires():
    """Suppression is a named list, not a general excuse to miss cards."""
    assert scan("4539578763621486") != []


# --------------------------------------------------------------------------
# Confidence: this tier knows WHAT, never WHOSE
# --------------------------------------------------------------------------

def test_checksum_hits_are_not_full_confidence():
    """A valid Luhn number is strong evidence of a card and no evidence at
    all about whose card it is. Only the known-value tier can say that."""
    assert scan("4539578763621486")[0].confidence < 1.0


def test_credential_hits_are_full_confidence():
    assert scan("AKIAIOSFODNN7EXAMPLE")[0].confidence == 1.0


def test_overlapping_matches_resolve_to_one():
    hits = scan("Card 4539578763621486 on file")
    assert len(hits) == 1
