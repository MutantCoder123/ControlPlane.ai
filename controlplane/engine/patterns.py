"""Structured-secret tier - TRACK A owns this.

Pattern PLUS checksum, never pattern alone (IDEATION section 9.1). The
checksums are the whole point: without Luhn, every long order number reads as
a payment card, and we drown the user in false positives - which is exactly
the alert fatigue the Round 2 brief calls out by name.

That is also why there is no phone-number pattern here. A ten-digit Indian
mobile has no checksum, so a pattern for it would be a guess, and guesses
belong in the known-value tier where we can be certain.

WHAT THIS TIER IS FOR
---------------------
It is the FLOOR under the ungoverned half of the estate (D28). Known-value
matching is the ceiling: deterministic, with a record reference, wherever the
organisation has actually classified its data. Where it has not - shared
drives, wikis, a CRM nobody curates - there is no classification to inherit,
and this tier is what stops coverage falling to zero.

Findings from here carry NO record_ref and a lower confidence than a
known-value hit, and that difference is deliberate: "matched customer record
44219" and "looks like a card number" are not the same claim and should not
be reported as if they were.

"TEST DATA STOPS FIRING"
------------------------
IDEATION section 9.2 claims 4111 1111 1111 1111 does not fire. On the
known-value tier that is true by construction - it is not in the customer
database. But this tier would still flag it on shape alone, because a valid
Luhn number is a valid Luhn number.

So we ship the card networks' PUBLISHED test numbers as an explicit
suppression list. That keeps the claim literally true and deterministic
rather than approximately true, and it is the same principle as the rest of
the design: we suppress values we KNOW are test data, we do not guess from
shape.

D10 - this tier is a prototype stand-in for a real NER model. It catches
structured secrets deterministically and unstructured PII not at all unless
the value is in the known-value store. Stated openly rather than hidden.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# --------------------------------------------------------------------------
# Checksums - what makes this tier deterministic instead of a guess
# --------------------------------------------------------------------------


def luhn_valid(digits: str) -> bool:
    """Mod-10, used by every major payment card network."""
    if not digits.isdigit() or not 12 <= len(digits) <= 19:
        return False
    total = 0
    for i, ch in enumerate(reversed(digits)):
        d = int(ch)
        if i % 2 == 1:
            d *= 2
            if d > 9:
                d -= 9
        total += d
    return total % 10 == 0


# Verhoeff tables - dihedral group D5. Catches transpositions that Luhn misses,
# which is why UIDAI chose it for Aadhaar.
_VERHOEFF_D = (
    (0, 1, 2, 3, 4, 5, 6, 7, 8, 9),
    (1, 2, 3, 4, 0, 6, 7, 8, 9, 5),
    (2, 3, 4, 0, 1, 7, 8, 9, 5, 6),
    (3, 4, 0, 1, 2, 8, 9, 5, 6, 7),
    (4, 0, 1, 2, 3, 9, 5, 6, 7, 8),
    (5, 9, 8, 7, 6, 0, 4, 3, 2, 1),
    (6, 5, 9, 8, 7, 1, 0, 4, 3, 2),
    (7, 6, 5, 9, 8, 2, 1, 0, 4, 3),
    (8, 7, 6, 5, 9, 3, 2, 1, 0, 4),
    (9, 8, 7, 6, 5, 4, 3, 2, 1, 0),
)
_VERHOEFF_P = (
    (0, 1, 2, 3, 4, 5, 6, 7, 8, 9),
    (1, 5, 7, 6, 2, 8, 3, 0, 9, 4),
    (5, 8, 0, 3, 7, 9, 6, 1, 4, 2),
    (8, 9, 1, 6, 0, 4, 3, 5, 2, 7),
    (9, 4, 5, 3, 1, 2, 6, 8, 7, 0),
    (4, 2, 8, 6, 5, 7, 3, 9, 0, 1),
    (2, 7, 9, 3, 8, 0, 6, 4, 1, 5),
    (7, 0, 4, 6, 9, 1, 3, 2, 5, 8),
)


def verhoeff_valid(digits: str) -> bool:
    """Aadhaar's checksum. 12 digits, and the first may not be 0 or 1."""
    if not digits.isdigit() or len(digits) != 12 or digits[0] in "01":
        return False
    check = 0
    for i, ch in enumerate(reversed(digits)):
        check = _VERHOEFF_D[check][_VERHOEFF_P[i % 8][int(ch)]]
    return check == 0


def mod97_valid(iban: str) -> bool:
    """ISO 13616 IBAN check."""
    compact = re.sub(r"\s+", "", iban).upper()
    if not re.fullmatch(r"[A-Z]{2}\d{2}[A-Z0-9]{10,30}", compact):
        return False
    rearranged = compact[4:] + compact[:4]
    numeric = "".join(
        str(ord(c) - 55) if c.isalpha() else c for c in rearranged
    )
    return int(numeric) % 97 == 1


# --------------------------------------------------------------------------
# Published test values - see module docstring
# --------------------------------------------------------------------------

#: Card numbers the networks publish for testing. Valid Luhn, never real.
KNOWN_TEST_VALUES = frozenset(
    {
        "4111111111111111",  # Visa
        "4012888888881881",  # Visa
        "4222222222222",     # Visa, 13-digit
        "4242424242424242",  # Stripe's canonical test card
        "5555555555554444",  # Mastercard
        "5105105105105100",  # Mastercard
        "378282246310005",   # Amex
        "371449635398431",   # Amex
        "6011111111111117",  # Discover
        "3530111333300000",  # JCB
    }
)


def is_known_test_value(digits: str) -> bool:
    return "".join(ch for ch in digits if ch.isdigit()) in KNOWN_TEST_VALUES


# --------------------------------------------------------------------------
# Patterns
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class PatternHit:
    span: tuple[int, int]
    text: str
    category: str
    action: str          # "block" | "substitute"
    confidence: float


@dataclass(frozen=True)
class _Rule:
    name: str
    category: str
    action: str
    regex: re.Pattern[str]
    validator: object | None      # callable or None
    confidence: float


def _digits(s: str) -> str:
    return "".join(ch for ch in s if ch.isdigit())


# Credentials block, PII substitutes (IDEATION section 9.5). There is no
# legitimate reason to send an API key to a model, and refusing costs the user
# nothing - whereas blocking every prompt containing customer data would block
# the entire reason they bought the tool.
_RULES: list[_Rule] = [
    _Rule(
        "openai_key", "api_key", "block",
        re.compile(r"\bsk-(?:proj-)?[A-Za-z0-9_-]{20,}\b"), None, 1.0,
    ),
    _Rule(
        "anthropic_key", "api_key", "block",
        re.compile(r"\bsk-ant-[A-Za-z0-9_-]{20,}\b"), None, 1.0,
    ),
    _Rule(
        "github_token", "api_key", "block",
        re.compile(r"\bgh[pousr]_[A-Za-z0-9]{36,}\b"), None, 1.0,
    ),
    _Rule(
        "aws_access_key", "api_key", "block",
        re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b"), None, 1.0,
    ),
    _Rule(
        "slack_token", "api_key", "block",
        re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}\b"), None, 1.0,
    ),
    _Rule(
        "private_key_block", "private_key", "block",
        re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH |PGP )?PRIVATE KEY-----"), None, 1.0,
    ),
    _Rule(
        "jwt", "jwt", "block",
        re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{4,}\b"),
        None, 1.0,
    ),
    _Rule(
        "payment_card", "payment_card", "substitute",
        re.compile(r"\b(?:\d[ -]?){12,18}\d\b"),
        lambda s: luhn_valid(_digits(s)), 0.9,
    ),
    _Rule(
        "aadhaar", "aadhaar", "substitute",
        re.compile(r"\b[2-9]\d{3}[ -]?\d{4}[ -]?\d{4}\b"),
        lambda s: verhoeff_valid(_digits(s)), 0.9,
    ),
    _Rule(
        "iban", "iban", "substitute",
        re.compile(r"\b[A-Z]{2}\d{2}[ ]?(?:[A-Z0-9]{4}[ ]?){2,7}[A-Z0-9]{1,4}\b"),
        mod97_valid, 0.9,
    ),
]


def scan(text: str) -> list[PatternHit]:
    """Every structured secret in `text`, non-overlapping, highest first.

    Confidence is deliberately below 1.0 for the checksum rules: a valid Luhn
    number is strong evidence of a card and no evidence at all about WHOSE
    card. Only the known-value tier can say that, and only where the
    organisation classified its data.
    """
    hits: list[PatternHit] = []
    for rule in _RULES:
        for m in rule.regex.finditer(text):
            matched = m.group(0)
            if rule.validator is not None and not rule.validator(matched):
                continue
            if is_known_test_value(matched):
                # Published test data. Suppressed deterministically, not
                # guessed at - see module docstring.
                continue
            hits.append(
                PatternHit(
                    span=m.span(),
                    text=matched,
                    category=rule.category,
                    action=rule.action,
                    confidence=rule.confidence,
                )
            )
    return _drop_overlaps(hits)


def _drop_overlaps(hits: list[PatternHit]) -> list[PatternHit]:
    """Keep the strongest, then the longest, when spans collide."""
    ordered = sorted(hits, key=lambda h: (-h.confidence, -(h.span[1] - h.span[0]), h.span[0]))
    kept: list[PatternHit] = []
    for hit in ordered:
        if any(hit.span[0] < k.span[1] and k.span[0] < hit.span[1] for k in kept):
            continue
        kept.append(hit)
    return sorted(kept, key=lambda h: h.span[0])
