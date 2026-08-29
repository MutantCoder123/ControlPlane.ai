"""Placeholder format - TRACK A owns this. Build it FIRST.

D15 (severity: could lose the panel) lives here. Detection is the easy half;
the hard half is that the model does not hand the token back unchanged. It
writes possessives, changes case, wraps it in quotes or JSON, splits it across
a line break. Naive str.replace() handles none of that.

Pick the format, write the adversarial tests, THEN write the matcher.
See TRACK-A.md step 1 for the full case table.

Track B must never hardcode this format (CONTRACTS.md section 4) - it imports
PLACEHOLDER_RE / is_placeholder from here instead.
"""

# TODO(Track A): decide the format before writing anything else.
PLACEHOLDER_RE = None


def make_placeholder(category: str, index: int) -> str:
    raise NotImplementedError("Track A - see TRACK-A.md step 1")


def is_placeholder(s: str) -> bool:
    raise NotImplementedError("Track A - see TRACK-A.md step 1")
