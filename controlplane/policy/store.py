"""The control plane and the data plane's view of it.

IDEATION section 16:

    Data plane (the checkpoint) - many instances, stateless, holds policy as
    a compiled in-memory artefact, makes ZERO network calls on the hot path.
    Deliberately dumb and fast.

    Control plane (the command centre) - policy authoring, budget ledger,
    dashboard, audit log. Rules are pushed to checkpoints in advance.

`ControlPlane` is the authoring side: it reads definitions, compiles them,
and publishes a versioned bundle. `PolicyStore` is what a checkpoint holds -
a dict lookup and nothing else.

Publishing is atomic: a request either sees the whole old bundle or the whole
new one, never half of each. That is what makes demo step 7 - change a policy
live, rerun, get a different result - safe to do on stage with traffic
flowing.

D20 is closed by this module: the split is now true in code rather than
asserted in a README, which matters more now that the repo is public (D23).
"""

from __future__ import annotations

import json
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from controlplane.policy.profile import PolicyError, Profile, compile_profile

DEFAULT_PROFILE_DIR = Path(__file__).parent / "profiles"
BASE_FILENAME = "_base.json"


@dataclass(frozen=True)
class PolicyBundle:
    """An immutable set of compiled profiles, versioned as a whole.

    Versioning the bundle rather than each profile is deliberate: "checkpoint
    7 is running bundle 3" is a question an operator can answer, whereas a
    per-profile version leaves you reconciling five numbers.
    """

    version: int
    profiles: dict[str, Profile]
    published_at: str
    source: str = ""

    def get(self, name: str) -> Profile | None:
        return self.profiles.get(name)

    @property
    def names(self) -> list[str]:
        return sorted(self.profiles)

    @property
    def fingerprints(self) -> dict[str, str]:
        return {n: p.fingerprint for n, p in sorted(self.profiles.items())}


class PolicyStore:
    """What the data plane holds. A dict lookup, and nothing else.

    No I/O, no network, no compilation. Everything expensive already happened
    in the control plane.
    """

    def __init__(self, bundle: PolicyBundle, default_profile: str | None = None) -> None:
        self._bundle = bundle
        self._default = default_profile
        self._lock = threading.Lock()
        self._listeners: list = []

    # -- hot path ----------------------------------------------------------

    def profile_for(self, name: str | None) -> Profile:
        """Resolve a request's profile. Raises rather than guessing.

        An unknown profile name must not silently fall back to something
        permissive - that is a security downgrade dressed as robustness. The
        gateway should refuse the request instead.
        """
        bundle = self._bundle          # single read: publish swaps atomically
        wanted = name or self._default
        if wanted is None:
            raise PolicyError("no profile specified and no default configured")
        profile = bundle.get(wanted)
        if profile is None:
            raise PolicyError(
                f"unknown profile {wanted!r}; known profiles: {bundle.names}"
            )
        return profile

    @property
    def bundle(self) -> PolicyBundle:
        return self._bundle

    @property
    def version(self) -> int:
        return self._bundle.version

    # -- publishing --------------------------------------------------------

    def publish(self, bundle: PolicyBundle) -> PolicyBundle:
        """Swap the whole bundle atomically and notify listeners.

        A single reference assignment, so an in-flight request either sees
        the entire old bundle or the entire new one. Half-applied policy is
        the failure mode that makes live changes frightening; this removes it.
        """
        with self._lock:
            previous = self._bundle
            self._bundle = bundle
        for listener in list(self._listeners):
            listener(previous, bundle)
        return previous

    def on_publish(self, listener) -> None:
        """Register a callback - used to write policy changes to the audit log."""
        self._listeners.append(listener)


class ControlPlane:
    """Authoring side: read definitions, compile, validate, publish."""

    def __init__(self, profile_dir: str | Path = DEFAULT_PROFILE_DIR) -> None:
        self.profile_dir = Path(profile_dir)
        self._version = 0

    def compile_bundle(self, overrides: dict[str, dict] | None = None) -> PolicyBundle:
        """Compile every definition on disk into one versioned bundle.

        `overrides` patches definitions in memory without touching the files -
        which is how the dashboard changes a policy live without needing
        write access to the repo.
        """
        base = self._read(self.profile_dir / BASE_FILENAME) if (
            self.profile_dir / BASE_FILENAME
        ).exists() else {}
        base.pop("name", None)

        profiles: dict[str, Profile] = {}
        for path in sorted(self.profile_dir.glob("*.json")):
            if path.name == BASE_FILENAME:
                continue
            definition = self._read(path)
            if overrides and definition.get("name") in overrides:
                definition = _deep_patch(definition, overrides[definition["name"]])
            profile = compile_profile(definition, base=base)
            if profile.name in profiles:
                raise PolicyError(f"duplicate profile name {profile.name!r}")
            profiles[profile.name] = profile

        if not profiles:
            raise PolicyError(f"no profile definitions found in {self.profile_dir}")

        self._version += 1
        return PolicyBundle(
            version=self._version,
            profiles=profiles,
            published_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
            source=str(self.profile_dir),
        )

    def store(self, default_profile: str | None = None) -> PolicyStore:
        """Compile once and hand the data plane its artefact."""
        return PolicyStore(self.compile_bundle(), default_profile=default_profile)

    @staticmethod
    def _read(path: Path) -> dict:
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise PolicyError(f"{path.name}: invalid JSON - {exc}") from exc


def _deep_patch(definition: dict, patch: dict) -> dict:
    out = dict(definition)
    for key, value in patch.items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = _deep_patch(out[key], value)
        else:
            out[key] = value
    return out
