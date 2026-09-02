"""The declared-vs-enforced map has to stay true, or it is just another claim.

The audit that produced this map (EXPLAINED.md section 8.2) found six profile
fields shown on the dashboard that nothing read. Cleaning that up once would
not stop it recurring - the next field added to `Profile` would be undeclared
and invisible again. So the map is checked against the dataclasses themselves:
add a field without declaring its state and the build goes red.
"""

from dataclasses import fields

import pytest

from controlplane.policy.enforcement import ENFORCEMENT, as_payload, state, unenforced
from controlplane.policy.profile import Profile, compile_profile

_SECTIONS = ("inbound", "outbound", "streaming", "decision", "quality", "cost", "session")


def _every_field_key() -> set[str]:
    """Every addressable field on a compiled Profile, as "section.field"."""
    keys = set()
    for f in fields(Profile):
        if f.name in _SECTIONS:
            for sub in fields(f.type if not isinstance(f.type, str) else object):
                keys.add(f"{f.name}.{sub.name}")
        else:
            keys.add(f.name)
    return keys


def test_every_profile_field_declares_whether_it_is_enforced():
    """The guard that stops section 8.2 happening a second time."""
    p = compile_profile({"name": "a"})
    keys = set()
    for f in fields(Profile):
        if f.name in _SECTIONS:
            section = getattr(p, f.name)
            for sub in fields(section):
                keys.add(f"{f.name}.{sub.name}")
        else:
            keys.add(f.name)

    undeclared = keys - set(ENFORCEMENT)
    assert not undeclared, (
        f"these Profile fields are not declared in policy/enforcement.py: "
        f"{sorted(undeclared)}. Add an entry saying whether behaviour reads it - "
        f"a field nobody declares is how EXPLAINED section 8.2 happened."
    )


def test_the_map_does_not_describe_fields_that_no_longer_exist():
    """Drift in the other direction: a field is deleted, its claim lingers."""
    p = compile_profile({"name": "a"})
    keys = set()
    for f in fields(Profile):
        if f.name in _SECTIONS:
            for sub in fields(getattr(p, f.name)):
                keys.add(f"{f.name}.{sub.name}")
        else:
            keys.add(f.name)

    stale = set(ENFORCEMENT) - keys
    assert not stale, f"policy/enforcement.py describes fields that do not exist: {sorted(stale)}"


def test_an_undeclared_key_reads_as_unenforced_not_as_fine():
    """Failing open on a *claim* is the wrong direction - an unknown field is
    reported as not enforced, never as working."""
    s = state("quality.something_invented")
    assert s.enforced is False
    assert "UNDECLARED" in s.note


def test_every_entry_carries_a_reason():
    """"enforced: false" with no explanation is the same vapour in a new place."""
    for key, st in ENFORCEMENT.items():
        assert st.note.strip(), f"{key} has no note"


def test_the_fields_the_demo_leans_on_are_actually_enforced():
    """The three the video points at by name. If one of these ever flips to
    false, a demo beat is asserting something the code stopped doing."""
    for key in ("decision.block_at", "streaming.overlap_chars",
                "session.max_records_per_session", "geography",
                "inbound.block_credentials"):
        assert ENFORCEMENT[key].enforced, f"{key} is load-bearing in the demo"


def test_the_payload_is_serialisable_and_complete():
    payload = as_payload()
    assert set(payload) == set(ENFORCEMENT)
    assert all({"enforced", "note"} == set(v) for v in payload.values())


def test_unenforced_list_matches_the_map():
    assert set(unenforced()) == {k for k, v in ENFORCEMENT.items() if not v.enforced}
