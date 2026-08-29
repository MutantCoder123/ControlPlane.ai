"""Placeholder format - TRACK A owns this. Built first, on purpose.

D15 lives here: restoration fidelity is the sharp edge, not detection.
Demo step 3 is fifteen seconds long and it is the whole pitch. If the model
returns `[[CUST_A]]'s account` and we render that to a judge, the
differentiator dies in front of them.

THE DESIGN DECISION
-------------------
Delimiters are the fragile part, not the token. A model that drops a bracket
breaks any matcher that requires brackets. So the format carries a core that
is independently recognisable - `CUST_A` - wrapped in `[[ ]]` for readability
in logs and prompts:

    [[CUST_A]]   [[EMAIL_B]]   [[ACCT_A]]

and there are TWO matchers, deliberately not one:

- `PLACEHOLDER_RE` - the global scanner. Requires at least one bracket, so
  ordinary prose like "PART_A of the agreement" is not flagged. Used to find
  UNRESTORED placeholders in output, which is our D15 alarm. A noisy alarm is
  a disabled alarm, so this one is strict.

- `tolerant_pattern(p)` - built per known placeholder, for restoration. Here
  brackets are OPTIONAL, whitespace is allowed inside, and case is ignored,
  because we already know the exact token we are hunting. False-positive risk
  is bounded to "the text happens to contain the token we just generated."

Restoration is mapping-driven, never regex-driven: we only ever put back
values for placeholders we ourselves created this request.

Track B imports PLACEHOLDER_RE / is_placeholder from here and must never
hardcode the format (CONTRACTS.md section 4).
"""

from __future__ import annotations

import re

# Core shape: CODE _ LABEL   e.g. CUST_A, EMAIL_B, ACCT_AA
_CORE = r"([A-Z][A-Z0-9]{1,7})\s*_\s*([A-Z]{1,4}\d*)"

#: Global scanner. At least one bracket each side - see module docstring.
PLACEHOLDER_RE = re.compile(r"\[{1,2}\s*" + _CORE + r"\s*\]{1,2}", re.IGNORECASE)

_FULL_RE = re.compile(r"\s*\[{1,2}\s*" + _CORE + r"\s*\]{1,2}\s*", re.IGNORECASE)

#: Short codes keep placeholders readable in a prompt. A model reasons better
#: about `[[CUST_A]]` than about `[[E7F3]]`, and the audit line reads better too.
_CATEGORY_CODES = {
    "customer_name": "CUST",
    "employee_name": "EMP",
    "email": "EMAIL",
    "phone": "PHONE",
    "account_number": "ACCT",
    "payment_card": "CARD",
    "aadhaar": "UID",
    "iban": "IBAN",
    "employee_id": "EMPID",
    "api_key": "KEY",
    "jwt": "TOKEN",
    "address": "ADDR",
}


def _code_for(category: str) -> str:
    """Short uppercase code for a category, with a safe fallback.

    Unknown categories are expected: the whole point of known-value matching
    is that we handle internal formats nobody wrote a pattern for
    (IDEATION section 9.2), so the category string may be anything the
    customer's own classification uses.
    """
    if category in _CATEGORY_CODES:
        return _CATEGORY_CODES[category]

    cleaned = "".join(ch for ch in category.upper() if ch.isalnum())[:6]
    if not cleaned:
        cleaned = "VAL"
    if not cleaned[0].isalpha():
        cleaned = "X" + cleaned[:5]
    if len(cleaned) < 2:
        cleaned += "X"
    return cleaned


def _label(index: int) -> str:
    """0 -> A, 25 -> Z, 26 -> AA. Never collides, stays short."""
    if index < 0:
        raise ValueError("placeholder index must be non-negative")
    out = ""
    n = index + 1
    while n:
        n, rem = divmod(n - 1, 26)
        out = chr(ord("A") + rem) + out
    return out


def make_placeholder(category: str, index: int) -> str:
    """Build the canonical placeholder for one entity in one request.

    Same category and index always give the same token, which is what lets
    the same entity map to the same placeholder throughout a request so
    relational reasoning survives substitution (IDEATION section 9.3).
    """
    return f"[[{_code_for(category)}_{_label(index)}]]"


def is_placeholder(text: str) -> bool:
    """True if the whole string is a placeholder, degraded forms included."""
    return bool(text) and bool(_FULL_RE.fullmatch(text))


def find_placeholders(text: str) -> list[str]:
    """Every placeholder-shaped token in `text`.

    Used to populate `RestoreResult.unrestored` - anything still here after
    restoration is a D15 failure and should fail a test, not log a warning.
    """
    return [m.group(0) for m in PLACEHOLDER_RE.finditer(text)]


def tolerant_pattern(placeholder: str) -> re.Pattern[str]:
    """Matcher for one known placeholder, tolerant of what models do to it.

    Survives: lost or doubled brackets, case changes, whitespace inside the
    braces, and a line break falling on the underscore. Consumes the
    delimiters so restoration cannot leave `[[Priya Sharma]]` on screen.

    Deliberately does NOT consume trailing punctuation: the apostrophe in
    `[[CUST_A]]'s balance` belongs to the sentence, not to us, and eating it
    would produce "Priya Sharma balance".

    Two alternatives rather than one optional-bracket pattern, because those
    two cases need different boundaries:

    - bracketed - the brackets themselves terminate the token, so
      `[[CUST_A]]s` can safely keep its plural `s`.
    - bare (brackets lost) - needs an explicit non-alphanumeric boundary, or
      the matcher for `CUST_A` happily matches the prefix of `CUST_AA` and
      restores the wrong entity's value. With 26+ entities in one request
      that is a real collision, not a theoretical one.
    """
    core = placeholder.strip("[] \t\r\n")
    parts = [re.escape(p) for p in core.split("_") if p]
    body = r"\s*_\s*".join(parts)
    bracketed = r"\[{1,2}\s*" + body + r"\s*\]{1,2}"
    bare = r"(?<![A-Za-z0-9_])" + body + r"(?![A-Za-z0-9_])"
    return re.compile(f"(?:{bracketed}|{bare})", re.IGNORECASE)
