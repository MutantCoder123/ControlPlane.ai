"""Adversarial round-trip tests for the placeholder format.

This file exists because of D15, the only drawback rated "could lose the
panel" for failing LIVE ON STAGE rather than in Q&A. Demo step 3 is fifteen
seconds long and it is the whole pitch; if the model hands back
`[[CUST_A]]'s account` and we render that to a judge, the differentiator dies
in front of them.

Detection is the easy half. The hard half is that the model does not return
our token unchanged. Every case below is something a real model actually does.

Written before the implementation, deliberately.
"""

import re

import pytest

from controlplane.engine.placeholders import (
    PLACEHOLDER_RE,
    find_placeholders,
    is_placeholder,
    make_placeholder,
    tolerant_pattern,
)


# --------------------------------------------------------------------------
# Format basics
# --------------------------------------------------------------------------

def test_make_placeholder_is_stable():
    """Same category and index must always give the same token."""
    assert make_placeholder("customer_name", 0) == make_placeholder("customer_name", 0)


def test_distinct_indices_give_distinct_placeholders():
    a = make_placeholder("customer_name", 0)
    b = make_placeholder("customer_name", 1)
    assert a != b


def test_distinct_categories_give_distinct_placeholders():
    assert make_placeholder("customer_name", 0) != make_placeholder("email", 0)


def test_index_runs_past_z():
    """26 entities in one request must not collide."""
    seen = {make_placeholder("customer_name", i) for i in range(60)}
    assert len(seen) == 60


def test_unknown_category_still_produces_a_valid_placeholder():
    p = make_placeholder("some_internal_format_we_never_saw", 0)
    assert is_placeholder(p)


def test_placeholder_is_ascii():
    """Non-ASCII delimiters get mangled by encodings and tokenizers."""
    assert make_placeholder("customer_name", 0).isascii()


# --------------------------------------------------------------------------
# The adversarial table from TRACK-A.md step 1
# --------------------------------------------------------------------------

CANON = None  # filled by the fixture below


@pytest.fixture()
def ph():
    return make_placeholder("customer_name", 0)


def _degradations(p: str) -> dict[str, str]:
    """How a model actually mangles a token, keyed by what it did."""
    core = p.strip("[]")
    return {
        "canonical": p,
        "possessive": f"{p}'s",
        "possessive_curly": f"{p}’s",
        "pluralised": f"{p}s",
        "lowercased": p.lower(),
        "trailing_comma": f"{p},",
        "full_stop": f"{p}.",
        "parenthesised": f"({p})",
        "in_backticks": f"`{p}`",
        "in_json": f'{{"name": "{p}"}}',
        "single_brackets": f"[{core}]",
        "no_brackets": core,
        "inner_space": f"[[ {core} ]]",
        "line_wrapped": p.replace("_", "_\n"),
    }


def test_every_degradation_is_still_found(ph):
    """The tolerant per-token pattern must survive all of it.

    This is the test that matters. A naive str.replace() passes only
    'canonical' and fails the other thirteen.
    """
    pat = tolerant_pattern(ph)
    failures = [name for name, text in _degradations(ph).items() if not pat.search(text)]
    assert not failures, f"tolerant pattern missed: {failures}"


def test_restoration_leaves_no_bracket_artefacts(ph):
    """Replacing must consume the delimiters, not leave them stranded.

    The stage failure mode: we swap the inner token but leave '[[' behind,
    and the judge sees [[Priya Sharma]].
    """
    pat = tolerant_pattern(ph)
    for name, text in _degradations(ph).items():
        out = pat.sub("Priya Sharma", text)
        assert "[[" not in out and "]]" not in out, f"{name}: stranded brackets in {out!r}"
        assert "Priya Sharma" in out, f"{name}: substitution did not happen"


def test_possessive_survives_restoration(ph):
    """`[[CUST_A]]'s balance` must become `Priya Sharma's balance`.

    The apostrophe belongs to the sentence, not to our token - it must NOT be
    eaten along with the placeholder.
    """
    out = tolerant_pattern(ph).sub("Priya Sharma", f"{ph}'s balance")
    assert out == "Priya Sharma's balance"


def test_json_context_survives_restoration(ph):
    out = tolerant_pattern(ph).sub("Priya Sharma", f'{{"name": "{ph}"}}')
    assert out == '{"name": "Priya Sharma"}'


def test_repeated_placeholder_all_replaced(ph):
    text = f"{ph} called. Later {ph} called again, and {ph} left."
    out = tolerant_pattern(ph).sub("Priya Sharma", text)
    assert "CUST" not in out.upper()
    assert out.count("Priya Sharma") == 3


# --------------------------------------------------------------------------
# Not matching things that are not ours - the false-restore risk
# --------------------------------------------------------------------------

@pytest.mark.parametrize(
    "text",
    [
        "The customer said hello.",
        "See section [A] of the policy.",
        "PART_A of the agreement",          # bare uppercase word, no brackets
        "Array index arr[0] is fine.",
        "[[TODO]] needs no underscore",
        "",
    ],
)
def test_ordinary_text_is_not_a_placeholder(text):
    assert not PLACEHOLDER_RE.search(text), f"false positive on {text!r}"


def test_bare_core_is_not_globally_matched(ph):
    """Bare `CUST_A` must not match the GLOBAL scanner.

    Brackets are optional only in the per-token tolerant pattern, where we
    already know the exact token we are hunting. Making them optional
    globally would flag ordinary text like PART_A as an unrestored
    placeholder, and `unrestored` is our D15 alarm - a noisy alarm is a
    disabled alarm.
    """
    assert not PLACEHOLDER_RE.search(ph.strip("[]"))
    assert tolerant_pattern(ph).search(ph.strip("[]"))


# --------------------------------------------------------------------------
# is_placeholder / find_placeholders
# --------------------------------------------------------------------------

def test_is_placeholder_accepts_canonical_and_degraded(ph):
    assert is_placeholder(ph)
    assert is_placeholder(ph.lower())
    assert is_placeholder(f"[{ph.strip('[]')}]")


@pytest.mark.parametrize("text", ["hello", "[[TODO]]", "", "CUST_A", "[[cust a]]"])
def test_is_placeholder_rejects_non_placeholders(text):
    assert not is_placeholder(text)


def test_find_placeholders_reports_every_occurrence(ph):
    other = make_placeholder("email", 0)
    found = find_placeholders(f"{ph} and {other} and {ph} again")
    assert len(found) == 3


def test_find_placeholders_on_clean_text_is_empty():
    assert find_placeholders("A perfectly ordinary sentence.") == []


def test_placeholder_re_is_a_compiled_pattern():
    """Track B imports this directly (CONTRACTS section 4)."""
    assert isinstance(PLACEHOLDER_RE, re.Pattern)
