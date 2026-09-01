"""Jurisdiction floors (Phase 7).

The Round 2 brief names this directly: "regulatory expectations differ by
geography... and continue to evolve, so rigid, hard-coded rules age quickly."
`geography` existed as a `Profile` field before this and was read by nothing -
this is the mechanism that makes it real: a jurisdiction supplies a FLOOR that
every profile is clamped against. A profile may be stricter than its
jurisdiction demands; it may never be looser. Getting that backwards is how a
governance product lets a team quietly opt out of the law by editing their
own config.
"""

import pytest

from controlplane.policy.profile import PolicyError, compile_profile
from controlplane.policy.store import ControlPlane


@pytest.fixture(scope="module")
def control() -> ControlPlane:
    return ControlPlane()


def test_a_looser_profile_is_tightened_to_the_floor(control):
    """internal-knowledge asks to block at 0.90. The EU floor is 0.75."""
    plain = control.compile_bundle().get("internal-knowledge")
    eu = control.compile_bundle(jurisdiction="eu").get("internal-knowledge")

    assert plain.decision.block_at == 0.9
    assert eu.decision.block_at == 0.75
    assert eu.fingerprint != plain.fingerprint


def test_a_profile_already_stricter_than_the_floor_is_left_alone(control):
    """The guard on the whole idea: a floor that always overwrites is not a
    floor, it is a default. `internal-knowledge` sets its OWN session cap to
    3 for the demo - stricter than every jurisdiction's floor (10-25) - and
    none of them may loosen it back up.
    """
    plain = control.compile_bundle().get("internal-knowledge")
    assert plain.session.max_records_per_session == 3

    for code in ("eu", "in", "us"):
        clamped = control.compile_bundle(jurisdiction=code).get("internal-knowledge")
        assert clamped.session.max_records_per_session == 3, (
            f"{code} floor loosened a profile that was already stricter"
        )


def test_the_us_floor_changes_nothing(control):
    """Loosest of the three - our own defaults already clear it.

    Same fingerprint as the unclamped compile, for every profile: not
    approximately the same, IDENTICAL. That is the honest way to show a
    permissive floor rather than asserting it in prose.
    """
    plain = control.compile_bundle()
    us = control.compile_bundle(jurisdiction="us")
    for name in plain.names:
        assert us.get(name).fingerprint == plain.get(name).fingerprint


def test_review_band_high_follows_a_clamped_block_at(control):
    """A clamped block_at must not leave review_band's top edge above it -
    that would be dead space no signal could ever land in."""
    eu = control.compile_bundle(jurisdiction="eu").get("internal-knowledge")
    low, high = eu.decision.review_band
    assert high <= eu.decision.block_at


def test_boolean_floors_only_ever_turn_a_setting_on(control):
    """decision-support already reviews everything; the EU floor does not
    turn always_review off just because it isn't in the floor file. It DOES
    turn on outbound.scan_pii, which this profile leaves at the base
    default (False) rather than setting itself.
    """
    before = control.compile_bundle().get("decision-support")
    after = control.compile_bundle(jurisdiction="eu").get("decision-support")

    assert before.decision.always_review is True
    assert after.decision.always_review is True

    assert before.outbound.scan_pii is False
    assert after.outbound.scan_pii is True


def test_fields_with_no_safety_direction_are_untouched_by_any_floor(control):
    """cost.* and streaming.mode have no strictness direction - a floor must
    not silently start dictating a profile's latency or budget choices."""
    plain = control.compile_bundle().get("internal-knowledge")
    eu = control.compile_bundle(jurisdiction="eu").get("internal-knowledge")
    assert eu.cost == plain.cost
    assert eu.streaming.mode == plain.streaming.mode


def test_an_unknown_jurisdiction_is_refused_with_a_useful_message(control):
    with pytest.raises(PolicyError, match="unknown jurisdiction"):
        control.compile_bundle(jurisdiction="atlantis")


def test_omitting_a_jurisdiction_compiles_exactly_as_before(control):
    """No behaviour change for every existing caller that never passes one."""
    plain = control.compile_bundle()
    again = control.compile_bundle()
    for name in plain.names:
        # A profile's fingerprint depends only on its content, never on which
        # compile call produced it - the bundle VERSION may differ, the
        # profile itself must not.
        assert plain.get(name).fingerprint == again.get(name).fingerprint
        assert plain.get(name).to_dict() == again.get(name).to_dict()


def test_compile_profile_accepts_jurisdiction_directly():
    """The lower-level function, not just the store wrapper - `jurisdiction`
    is a plain dict of floor values, not a filename."""
    profile = compile_profile(
        {"name": "test"},
        jurisdiction={"decision": {"block_at": 0.5}},
    )
    assert profile.decision.block_at == 0.5


def test_list_jurisdictions_names_all_three(control):
    assert control.list_jurisdictions() == ["eu", "in", "us"]


def test_jurisdiction_info_carries_its_own_disclaimer(control):
    info = control.jurisdiction_info("eu")
    assert "not legal advice" in info["description"]
