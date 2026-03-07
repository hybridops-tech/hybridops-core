"""
purpose: Persist and read module state snapshots for dependency wiring.
Architecture Decision: ADR-N/A (module state)
maintainer: HybridOps.Studio
"""

from __future__ import annotations

from pathlib import Path
from typing import Any
import re

from hyops.runtime.refs import module_id_from_ref, normalize_module_ref
from hyops.runtime.state import read_json, write_json_atomic


_STATE_INSTANCE_RE = re.compile(r"^[a-z0-9][a-z0-9_.-]{0,63}$")
_STATE_REF_ALIASES: dict[str, tuple[str, ...]] = {
    "platform/postgresql-ha": ("platform/onprem/postgresql-ha",),
    "platform/onprem/postgresql-ha": ("platform/postgresql-ha",),
    "platform/postgresql-ha-backup": ("platform/onprem/postgresql-ha-backup",),
    "platform/onprem/postgresql-ha-backup": ("platform/postgresql-ha-backup",),
}


def normalize_state_instance(value: str | None) -> str | None:
    raw = str(value or "").strip().lower()
    if not raw:
        return None
    if not _STATE_INSTANCE_RE.fullmatch(raw):
        raise ValueError(
            "state_instance must match ^[a-z0-9][a-z0-9_.-]{0,63}$"
        )
    return raw


def split_module_state_ref(module_ref: str, *, state_instance: str | None = None) -> tuple[str, str | None]:
    raw_ref = str(module_ref or "").strip()
    if not raw_ref:
        raise ValueError("module_ref is required")

    from_ref_instance: str | None = None
    if "#" in raw_ref:
        base, suffix = raw_ref.split("#", 1)
        raw_ref = base.strip()
        from_ref_instance = normalize_state_instance(suffix)

    ref = normalize_module_ref(raw_ref)
    if not ref:
        raise ValueError(f"invalid module_ref: {module_ref!r}")

    explicit_instance = normalize_state_instance(state_instance)
    if from_ref_instance and explicit_instance and from_ref_instance != explicit_instance:
        raise ValueError(
            f"conflicting state_instance in module_ref and argument: {from_ref_instance!r} vs {explicit_instance!r}"
        )

    return ref, (explicit_instance or from_ref_instance)


def normalize_module_state_ref(module_ref: str, *, state_instance: str | None = None) -> str:
    ref, instance = split_module_state_ref(module_ref, state_instance=state_instance)
    if instance:
        return f"{ref}#{instance}"
    return ref


def _candidate_module_state_paths(state_root: Path, module_ref: str, *, state_instance: str | None = None) -> list[Path]:
    state_dir = Path(state_root).expanduser().resolve()
    ref, instance = split_module_state_ref(module_ref, state_instance=state_instance)
    refs = [ref, *[alias for alias in _STATE_REF_ALIASES.get(ref, ()) if alias and alias != ref]]
    paths: list[Path] = []
    for candidate_ref in refs:
        module_id = module_id_from_ref(candidate_ref)
        if not module_id:
            continue
        if instance:
            paths.append(state_dir / "modules" / module_id / "instances" / f"{instance}.json")
        else:
            paths.append(state_dir / "modules" / module_id / "latest.json")
    return paths


def module_state_path(state_root: Path, module_ref: str, *, state_instance: str | None = None) -> Path:
    state_dir = Path(state_root).expanduser().resolve()

    ref, instance = split_module_state_ref(module_ref, state_instance=state_instance)
    module_id = module_id_from_ref(ref)
    if not module_id:
        raise ValueError(f"invalid module_ref: {module_ref!r}")

    if instance:
        return state_dir / "modules" / module_id / "instances" / f"{instance}.json"

    return state_dir / "modules" / module_id / "latest.json"


def read_module_state(state_root: Path, module_ref: str, *, state_instance: str | None = None) -> dict[str, Any]:
    candidates = _candidate_module_state_paths(state_root, module_ref, state_instance=state_instance)
    if not candidates:
        raise FileNotFoundError(module_state_path(state_root, module_ref, state_instance=state_instance))

    path = next((candidate for candidate in candidates if candidate.exists()), candidates[0])
    if not path.exists():
        raise FileNotFoundError(path)

    payload = read_json(path)
    if not isinstance(payload, dict):
        raise ValueError(f"invalid module state file: {path}")
    return payload


def write_module_state(
    state_root: Path,
    module_ref: str,
    payload: dict[str, Any],
    *,
    state_instance: str | None = None,
) -> Path:
    if not isinstance(payload, dict):
        raise ValueError("payload must be a mapping")

    path = module_state_path(state_root, module_ref, state_instance=state_instance)
    write_json_atomic(path, payload, mode=0o600)
    return path
