"""Known-value store - TRACK A owns this.

Pattern matching asks "does this look like a secret?" We ask "is this OUR
secret?" (IDEATION section 9.2). The organisation already knows its own
sensitive data, so we hash every value it told us about and scan for those
hashes instead of guessing from shape.

That flips every weakness of regex at once:
  - unstructured PII becomes deterministic - we do not guess "Priya Sharma"
    is a name, we know she is customer 44219
  - internal formats nobody wrote a pattern for are covered
  - test data stops firing: 4111 1111 1111 1111 passes Luhn but is not ours
  - the audit line becomes "matched customer record 44219", not "matched a
    regex"

WE STORE HASHES, NEVER RAW VALUES. If someone dumps this process they must
not get a customer list - otherwise the compliance tool becomes the largest
concentration of sensitive data in the company (IDEATION section 18).

D9 - exact-match only. Normalisation buys case, whitespace, surrounding
punctuation and digit separators. It does NOT buy misspellings, nicknames or
transliteration. That is a stated limitation, not a TODO; production pairs
this with an NER model for the unknown-entity case.

D28 - only `governed` records are indexed. Ungoverned ones fall through to
the pattern tier, which is the floor under the half of the estate that has no
classification to inherit.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path

# Punctuation stripped from the OUTER edges of a token only. Inner punctuation
# survives, so emails and ids like E-3311 stay intact.
_EDGE_PUNCT = "\"'`.,;:!?()[]{}<>*_~|“”‘’ "

_TOKEN_RE = re.compile(r"\S+")
_WS_RE = re.compile(r"\s+")


def normalise(value: str) -> str:
    """Casefold, strip edge punctuation, collapse inner whitespace.

    Unicode-normalised first so a composed and a decomposed accent hash the
    same - otherwise two visually identical names miss each other.
    """
    text = unicodedata.normalize("NFKC", value)
    text = _WS_RE.sub(" ", text).strip()
    return text.strip(_EDGE_PUNCT).strip().casefold()


def digits_key(value: str) -> str | None:
    """Separator-insensitive key for numeric identifiers, or None.

    An account number pasted as "5010 0234 5678 90" is the same account as
    "50100234567890", and a human will paste it either way. Only applies when
    the value is essentially digits plus separators, so it cannot collapse a
    name into a number.
    """
    digits = "".join(ch for ch in value if ch.isdigit())
    if len(digits) < 6:
        return None
    non_digit = [ch for ch in value if not ch.isdigit()]
    if any(ch not in " -/." for ch in non_digit):
        return None
    return digits


def _fingerprint(key: str) -> bytes:
    return hashlib.blake2b(key.encode("utf-8"), digest_size=16).digest()


class _BloomFilter:
    """Cheap negative check in front of the hash set.

    Almost every n-gram we test is not a known value, so the filter is what
    keeps inbound scanning cheap - and inbound volume is the direction that
    must be cheap (IDEATION section 9.6).
    """

    __slots__ = ("_bits", "_m", "_k")

    def __init__(self, capacity: int, error_rate: float) -> None:
        capacity = max(1, capacity)
        m = max(8, math.ceil(-capacity * math.log(error_rate) / (math.log(2) ** 2)))
        self._m = m
        self._k = max(1, round((m / capacity) * math.log(2)))
        self._bits = bytearray((m + 7) // 8)

    def _positions(self, digest: bytes):
        h1 = int.from_bytes(digest[:8], "big")
        h2 = int.from_bytes(digest[8:], "big") | 1
        for i in range(self._k):
            yield (h1 + i * h2) % self._m

    def add(self, digest: bytes) -> None:
        for pos in self._positions(digest):
            self._bits[pos >> 3] |= 1 << (pos & 7)

    def __contains__(self, digest: bytes) -> bool:
        return all(
            self._bits[pos >> 3] & (1 << (pos & 7)) for pos in self._positions(digest)
        )


@dataclass(frozen=True)
class KnownMatch:
    """What we know about a value, without knowing the value."""

    record_ref: str      # "customer:44219" - the audit line
    category: str        # "customer_name", "account_number", ...
    role: str            # "identifier" | "operand"
    field_name: str


@dataclass(frozen=True)
class KnownHit:
    """A known value located in a piece of text."""

    span: tuple[int, int]
    text: str            # the matched slice of the ORIGINAL text
    match: KnownMatch


class KnownValueStore:
    """Hashes of the organisation's own sensitive values.

    Built from the seed records Track B produces (CONTRACTS.md section 2).
    """

    def __init__(self, capacity: int = 100_000, error_rate: float = 0.001) -> None:
        self._index: dict[bytes, KnownMatch] = {}
        self._bloom = _BloomFilter(capacity, error_rate)
        self._max_tokens = 1
        self._has_digit_keys = False
        self._records = 0
        self._skipped_ungoverned = 0

    #: A digit identifier can arrive split across tokens - "5010 0234 5678 90"
    #: is the same account as "50100234567890" and a human pastes whichever
    #: their screen showed. Capped so a long numeric table does not turn the
    #: scan quadratic.
    MAX_NUMERIC_TOKENS = 8

    # -- construction ------------------------------------------------------

    @classmethod
    def from_jsonl(cls, path: str | Path, **kwargs) -> "KnownValueStore":
        store = cls(**kwargs)
        with open(path, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if line:
                    store.add_record(json.loads(line))
        return store

    def add_record(self, record: dict) -> None:
        """Index one record. Ungoverned records are deliberately skipped."""
        if record.get("governance") != "governed":
            self._skipped_ungoverned += 1
            return

        record_ref = record["record_id"]
        self._records += 1
        for field in record.get("fields", []):
            self._add_value(
                field["value"],
                KnownMatch(
                    record_ref=record_ref,
                    category=field.get("category", "unknown"),
                    role=field.get("role", "identifier"),
                    field_name=field.get("name", ""),
                ),
            )

    def _add_value(self, value: str, match: KnownMatch) -> None:
        key = normalise(value)
        if not key:
            return
        self._register(key, match)

        alt = digits_key(value)
        if alt and alt != key:
            self._register(alt, match)
        if alt:
            self._has_digit_keys = True

        self._max_tokens = max(self._max_tokens, len(key.split(" ")))

    def _register(self, key: str, match: KnownMatch) -> None:
        digest = _fingerprint(key)
        # First writer wins, so a value shared by two records keeps a stable
        # audit reference instead of flapping between them.
        if digest not in self._index:
            self._index[digest] = match
            self._bloom.add(digest)

    # -- lookup ------------------------------------------------------------

    def lookup(self, candidate: str) -> KnownMatch | None:
        key = normalise(candidate)
        if not key:
            return None
        hit = self._lookup_key(key)
        if hit:
            return hit
        alt = digits_key(candidate)
        return self._lookup_key(alt) if alt else None

    def _lookup_key(self, key: str) -> KnownMatch | None:
        digest = _fingerprint(key)
        if digest not in self._bloom:      # cheap negative, the common case
            return None
        return self._index.get(digest)     # bloom false positives die here

    def scan(self, text: str) -> list[KnownHit]:
        """Every known value in `text`, longest match first, non-overlapping.

        Longest-first matters: once "Priya Sharma" matches as a customer name
        we must not also match "Priya" separately, or one entity becomes two
        placeholders and the model loses the thread.
        """
        tokens = _tokenise(text)
        hits: list[KnownHit] = []
        i = 0
        while i < len(tokens):
            run = _run_length(text, tokens, i)
            width = self._max_tokens
            if self._has_digit_keys:
                # A grouped account or card number spans more tokens than any
                # name does. Widen the window only across numeric tokens, so
                # the extra work is bounded to the places it can pay off.
                width = max(width, min(_numeric_run(tokens, i), self.MAX_NUMERIC_TOKENS))
            max_size = min(width, run)
            for size in range(max_size, 0, -1):
                window = tokens[i : i + size]
                candidate = " ".join(t[2] for t in window)
                match = self.lookup(candidate)
                if match:
                    hits.append(
                        KnownHit(
                            span=(window[0][0], window[-1][1]),
                            text=text[window[0][0] : window[-1][1]],
                            match=match,
                        )
                    )
                    i += size
                    break
            else:
                i += 1
        return hits

    # -- introspection -----------------------------------------------------

    def __len__(self) -> int:
        return len(self._index)

    @property
    def record_count(self) -> int:
        return self._records

    @property
    def skipped_ungoverned(self) -> int:
        """How many records had no classification to inherit (D28)."""
        return self._skipped_ungoverned

    def __repr__(self) -> str:
        # No raw values, by construction - there are none to leak.
        return (
            f"<KnownValueStore records={self._records} keys={len(self._index)} "
            f"ungoverned_skipped={self._skipped_ungoverned}>"
        )


def _run_length(text: str, tokens: list[tuple[int, int, str]], start: int) -> int:
    """How many tokens from `start` are separated by whitespace ALONE.

    Without this, "Send it to Priya. Sharma is a common surname." matches
    "Priya. Sharma" as a customer name, because the full stop is stripped as
    edge punctuation before the n-gram is joined. Substituting that would
    swallow the sentence boundary and change what the sentence says - a
    correctness bug and a false positive at the same time.

    Anything other than whitespace between two tokens (a full stop, a comma,
    a dash) ends the run.
    """
    n = 1
    while start + n < len(tokens):
        gap = text[tokens[start + n - 1][1] : tokens[start + n][0]]
        if gap and not gap.isspace():
            break
        n += 1
    return n


def _numeric_run(tokens: list[tuple[int, int, str]], start: int) -> int:
    """How many consecutive tokens from `start` are digits and separators."""
    n = 0
    while start + n < len(tokens):
        tok = tokens[start + n][2]
        if not tok or not all(ch.isdigit() or ch in "-/." for ch in tok):
            break
        if not any(ch.isdigit() for ch in tok):
            break
        n += 1
    return max(n, 1)


def _tokenise(text: str) -> list[tuple[int, int, str]]:
    """Whitespace tokens with edge punctuation trimmed, spans preserved.

    Spans refer to the ORIGINAL text - the gateway needs those offsets for
    the audit entry (CONTRACTS.md section 3).
    """
    out: list[tuple[int, int, str]] = []
    for m in _TOKEN_RE.finditer(text):
        start, end = m.span()
        raw = m.group()
        lead = len(raw) - len(raw.lstrip(_EDGE_PUNCT))
        trail = len(raw) - len(raw.rstrip(_EDGE_PUNCT))
        start += lead
        end -= trail
        if end > start:
            out.append((start, end, text[start:end]))
    return out
