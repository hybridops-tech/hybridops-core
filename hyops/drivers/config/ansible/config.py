"""Configuration/profile helpers for the Ansible config driver."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from hyops.runtime.coerce import as_argv, as_bool, as_int


def load_profile(profile_ref: str, profiles_dir: Path) -> tuple[dict[str, Any], Path, str]:
    path = (profiles_dir / f"{profile_ref}.profile.yml").resolve()
    if not path.exists():
        return {}, path, f"profile not found: {path}"

    try:
        payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except Exception as exc:
        return {}, path, f"profile parse failed: {exc}"

    if not isinstance(payload, dict):
        return {}, path, "profile must be a mapping"

    if str(payload.get("driver") or "").strip() not in ("", "config/ansible"):
        return {}, path, "profile.driver must be config/ansible"

    return payload, path, ""


def resolve_required_credentials(request: dict[str, Any]) -> list[str]:
    requirements = request.get("requirements")
    if not isinstance(requirements, dict):
        return []

    raw = requirements.get("credentials")
    if not isinstance(raw, list):
        return []

    out: list[str] = []
    seen: set[str] = set()
    for item in raw:
        token = str(item or "").strip().lower()
        if not token or token in seen:
            continue
        seen.add(token)
        out.append(token)
    return out


def resolve_required_env(inputs: dict[str, Any], *, key: str = "required_env") -> tuple[list[str], str]:
    raw = inputs.get(key)
    if raw is None:
        return [], ""
    if not isinstance(raw, list):
        return [], f"inputs.{key} must be a list when set"

    out: list[str] = []
    seen: set[str] = set()
    for idx, item in enumerate(raw, start=1):
        if not isinstance(item, str) or not item.strip():
            return [], f"inputs.{key}[{idx}] must be a non-empty string"
        token = item.strip()
        if token in seen:
            continue
        seen.add(token)
        out.append(token)

    return out, ""


def resolve_policy_defaults(profile: dict[str, Any]) -> tuple[int | None, int, bool]:
    policy = profile.get("policy")
    if not isinstance(policy, dict):
        return None, 0, True

    defaults = policy.get("defaults")
    if not isinstance(defaults, dict):
        return None, 0, True

    timeout_raw = as_int(defaults.get("command_timeout_s"), default=0)
    timeout_s = timeout_raw if timeout_raw > 0 else None
    retries = max(0, as_int(defaults.get("retries"), default=0))
    redact = as_bool(defaults.get("redact"), default=True)
    return timeout_s, retries, redact


def resolve_ansible_cfg(profile: dict[str, Any]) -> dict[str, Any]:
    raw = profile.get("ansible")
    if not isinstance(raw, dict):
        raw = {}

    return {
        "bin": str(raw.get("bin") or "ansible-playbook").strip() or "ansible-playbook",
        "apply_args": as_argv(raw.get("apply_args"), []),
        "plan_args": as_argv(raw.get("plan_args"), ["--check"]),
        "validate_args": as_argv(raw.get("validate_args"), ["--syntax-check"]),
        "destroy_args": as_argv(raw.get("destroy_args"), []),
        "inventory_file": str(raw.get("inventory_file") or "inventory.ini").strip() or "inventory.ini",
        "playbook_file": str(raw.get("playbook_file") or "playbook.yml").strip() or "playbook.yml",
        "destroy_playbook_file": str(raw.get("destroy_playbook_file") or "destroy.playbook.yml").strip()
        or "destroy.playbook.yml",
    }
