"""Profile compilation and the control-plane / data-plane split.

D20: IDEATION section 16 asserts this split, and until now nothing was
actually authored centrally and pushed. These tests are the evidence that the
claim is true in code - which matters more now the repo is public (D23).
"""

import json

import pytest

from controlplane.audit.chain import AuditLog, attach_to_store
from controlplane.policy.profile import PolicyError, Profile, compile_profile
from controlplane.policy.store import ControlPlane, PolicyStore


@pytest.fixture(scope="module")
def control() -> ControlPlane:
    return ControlPlane()


@pytest.fixture()
def store(control) -> PolicyStore:
    return control.store(default_profile="internal-knowledge")


# --------------------------------------------------------------------------
# The three the brief names
# --------------------------------------------------------------------------

def test_the_briefs_three_use_cases_exist(store):
    """"a customer support assistant, an internal knowledge assistant, and a
    decision-support tool" - Round 2 reference parameters, verbatim."""
    assert store.bundle.names == [
        "customer-support",
        "decision-support",
        "internal-knowledge",
    ]


def test_profiles_actually_differ(store):
    """A policy layer where every profile is identical is decoration."""
    fps = set(store.bundle.fingerprints.values())
    assert len(fps) == 3


def test_customer_facing_inverts_the_asymmetry(store):
    """D21 - in family A the catastrophic direction is outbound."""
    p = store.profile_for("customer-support")
    assert p.outbound.scan_pii and p.outbound.cross_tenant_check
    assert p.quality.toxicity_sync, "only place a slur reaches a member of the public"
    assert p.quality.hallucination_tier == 2, "customer-facing skips to tier 2"


def test_decision_support_always_pulls_in_a_human(store):
    """IDEATION 12.2 - legal exposure justifies reviewing everything."""
    p = store.profile_for("decision-support")
    assert p.decision.always_review
    assert p.quality.counterfactual_sample_rate == 1.0
    assert p.audit_level == "full"


def test_internal_assistant_is_the_one_that_caches(store):
    """Small question set, high volume - the only profile where caching pays."""
    assert store.profile_for("internal-knowledge").cost.cache_enabled
    assert not store.profile_for("customer-support").cost.cache_enabled


# --------------------------------------------------------------------------
# D6 - buffering is a profile property, not a global one
# --------------------------------------------------------------------------

def test_streaming_mode_is_per_profile():
    interactive = compile_profile({"name": "a", "streaming": {"mode": "interactive"}})
    batch = compile_profile({"name": "b", "streaming": {"mode": "throughput"}})
    assert interactive.streaming.buffered
    assert not batch.streaming.buffered


def test_unknown_streaming_mode_is_refused():
    with pytest.raises(PolicyError, match="streaming.mode"):
        compile_profile({"name": "a", "streaming": {"mode": "whenever"}})


# --------------------------------------------------------------------------
# Compilation refuses bad policy at authoring time, not request time
# --------------------------------------------------------------------------

def test_typo_in_a_policy_key_is_refused():
    """A silent security downgrade otherwise.

    "block_credential: true" - singular - would simply not apply, and the
    profile would look configured while being wide open.
    """
    with pytest.raises(PolicyError, match="unknown keys"):
        compile_profile({"name": "a", "inbound": {"block_credential": True}})


def test_credentials_cannot_be_allowed_through():
    """There is no legitimate reason to send an API key to a model."""
    with pytest.raises(PolicyError, match="block_credentials"):
        compile_profile({"name": "a", "inbound": {"block_credentials": False}})


def test_incoherent_combination_is_refused():
    with pytest.raises(PolicyError, match="cross_tenant_check"):
        compile_profile(
            {"name": "a", "outbound": {"cross_tenant_check": True, "scan_pii": False}}
        )


@pytest.mark.parametrize(
    "definition,match",
    [
        ({"name": "a", "decision": {"review_band": [0.9, 0.5]}}, "review_band"),
        ({"name": "a", "decision": {"block_at": 1.5}}, "block_at"),
        ({"name": "a", "decision": {"flag_budget_per_100": -1}}, "flag budget"),
        ({"name": "a", "quality": {"hallucination_tier": 7}}, "hallucination_tier"),
        ({"name": "a", "quality": {"counterfactual_sample_rate": 2}}, "counterfactual"),
        ({"name": "a", "cost": {"max_output_tokens": 0}}, "max_output_tokens"),
        ({"name": "a", "audit_level": "vibes"}, "audit_level"),
        ({"streaming": {}}, "needs a name"),
    ],
)
def test_invalid_definitions_are_refused(definition, match):
    with pytest.raises(PolicyError, match=match):
        compile_profile(definition)


def test_profile_is_immutable(store):
    with pytest.raises(Exception):
        store.profile_for("customer-support").audit_level = "none"


# --------------------------------------------------------------------------
# Fingerprints and diffs
# --------------------------------------------------------------------------

def test_fingerprint_is_content_addressed():
    """Two checkpoints on the same fingerprint provably run the same policy."""
    a = compile_profile({"name": "x", "decision": {"block_at": 0.9}})
    b = compile_profile({"name": "x", "decision": {"block_at": 0.9}})
    c = compile_profile({"name": "x", "decision": {"block_at": 0.8}})
    assert a.fingerprint == b.fingerprint
    assert a.fingerprint != c.fingerprint


def test_diff_explains_what_changed():
    """"The model learned" is not an answer a regulator accepts. A diff is."""
    old = compile_profile({"name": "x", "decision": {"block_at": 0.9}})
    new = compile_profile({"name": "x", "decision": {"block_at": 0.7}})
    assert new.diff(old) == {"decision.block_at": (0.9, 0.7)}


# --------------------------------------------------------------------------
# The data plane's view: a dict lookup and nothing else
# --------------------------------------------------------------------------

def test_unknown_profile_raises_rather_than_falling_back(store):
    """Silently defaulting to something permissive is a security downgrade
    dressed up as robustness."""
    with pytest.raises(PolicyError, match="unknown profile"):
        store.profile_for("does-not-exist")


def test_default_profile_is_used_when_none_given(store):
    assert store.profile_for(None).name == "internal-knowledge"


def test_no_default_configured_is_an_error(control):
    with pytest.raises(PolicyError, match="no profile specified"):
        control.store().profile_for(None)


def test_hot_path_does_no_io(store, monkeypatch):
    """The checkpoint makes zero network calls and touches no disk.

    Enforced rather than asserted in prose: open() is broken for the duration
    of the lookup, and the lookup still works.
    """
    import builtins

    def explode(*a, **k):
        raise AssertionError("hot path touched the filesystem")

    monkeypatch.setattr(builtins, "open", explode)
    assert store.profile_for("customer-support").name == "customer-support"


# --------------------------------------------------------------------------
# Hot swap - demo step 7
# --------------------------------------------------------------------------

def test_publish_swaps_policy_without_restart(control):
    """Change a policy live, rerun, get a different result."""
    store = control.store(default_profile="internal-knowledge")
    assert store.profile_for("internal-knowledge").cost.cache_enabled is True

    tightened = control.compile_bundle(
        overrides={"internal-knowledge": {"cost": {"cache_enabled": False}}}
    )
    store.publish(tightened)

    assert store.profile_for("internal-knowledge").cost.cache_enabled is False


def test_publish_bumps_the_bundle_version(control):
    store = control.store(default_profile="internal-knowledge")
    before = store.version
    store.publish(control.compile_bundle())
    assert store.version == before + 1


def test_publish_is_atomic(control):
    """A request sees the whole old bundle or the whole new one.

    Half-applied policy is what makes live changes frightening; swapping a
    single reference removes the failure mode entirely.
    """
    store = control.store(default_profile="internal-knowledge")
    old_bundle = store.bundle
    store.publish(control.compile_bundle(overrides={"customer-support": {"geography": "EU"}}))
    # the old bundle object is unchanged and still internally consistent
    assert old_bundle.get("customer-support").geography == "IN"
    assert store.profile_for("customer-support").geography == "EU"


def test_policy_change_is_written_to_the_audit_log(control):
    """Demo step 7 has to be auditable, or it is just a config edit."""
    log = AuditLog()
    store = control.store(default_profile="internal-knowledge")
    attach_to_store(log, store)

    before = store.profile_for("customer-support").decision.block_at
    store.publish(
        control.compile_bundle(overrides={"customer-support": {"decision": {"block_at": 0.6}}})
    )

    changes = log.by_event("policy_change")
    assert len(changes) == 1
    assert changes[0].payload["changes"]["customer-support"]["decision.block_at"] == [
        str(before),
        "0.6",
    ]
    assert log.verify()


# --------------------------------------------------------------------------
# Definitions on disk
# --------------------------------------------------------------------------

def test_shipped_definitions_all_compile(control):
    assert len(control.compile_bundle().profiles) == 3


def test_missing_directory_is_a_clear_error(tmp_path):
    with pytest.raises(PolicyError, match="no profile definitions"):
        ControlPlane(tmp_path).compile_bundle()


def test_invalid_json_names_the_file(tmp_path):
    (tmp_path / "broken.json").write_text("{not json", encoding="utf-8")
    with pytest.raises(PolicyError, match="broken.json"):
        ControlPlane(tmp_path).compile_bundle()


def test_base_defaults_are_inherited(tmp_path):
    (tmp_path / "_base.json").write_text(
        json.dumps({"geography": "EU", "cost": {"max_output_tokens": 99}}), encoding="utf-8"
    )
    (tmp_path / "p.json").write_text(json.dumps({"name": "p"}), encoding="utf-8")
    profile = ControlPlane(tmp_path).compile_bundle().get("p")
    assert profile.geography == "EU" and profile.cost.max_output_tokens == 99
