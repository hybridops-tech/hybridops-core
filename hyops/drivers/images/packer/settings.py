"""Profile/settings helpers for the Packer image driver."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import yaml

from hyops.runtime.coerce import as_argv, as_positive_int

_KEY_RE = re.compile(r"^[a-z0-9](?:[a-z0-9._-]*[a-z0-9])?$")


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
    if str(payload.get("driver") or "").strip() not in ("", "images/packer"):
        return {}, path, "profile.driver must be images/packer"
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
        if not _KEY_RE.fullmatch(token):
            continue
        seen.add(token)
        out.append(token)
    return out


def resolve_packer_settings(profile: dict[str, Any]) -> tuple[str, list[str], list[str], list[str]]:
    cfg = profile.get("packer")
    if not isinstance(cfg, dict):
        cfg = {}
    bin_name = str(cfg.get("bin") or "packer").strip() or "packer"
    init_args = as_argv(cfg.get("init_args"), ["init"])
    validate_args = as_argv(cfg.get("validate_args"), ["validate"])
    build_args = as_argv(cfg.get("build_args"), ["build", "-color=false"])
    return bin_name, init_args, validate_args, build_args


def resolve_timeout(profile: dict[str, Any]) -> int | None:
    policy = profile.get("policy")
    if not isinstance(policy, dict):
        return None
    defaults = policy.get("defaults")
    if not isinstance(defaults, dict):
        return None
    raw = defaults.get("command_timeout_s")
    value = as_positive_int(raw)
    return value if value and value > 0 else None


def resolve_credential_contract(profile: dict[str, Any], provider: str) -> list[str]:
    policy = profile.get("policy")
    if not isinstance(policy, dict):
        return []
    constraints = policy.get("constraints")
    if not isinstance(constraints, dict):
        return []
    contracts = constraints.get("credential_contracts")
    if not isinstance(contracts, dict):
        return []
    provider_block = contracts.get(provider)
    if not isinstance(provider_block, dict):
        return []
    raw = provider_block.get("required_tfvars")
    if not isinstance(raw, list):
        return []
    out: list[str] = []
    for item in raw:
        token = str(item or "").strip()
        if token:
            out.append(token)
    return out


def resolve_template_key(inputs: dict[str, Any], pack_cfg: dict[str, Any]) -> tuple[str, dict[str, Any], str]:
    templates = pack_cfg.get("templates")
    if not isinstance(templates, dict) or not templates:
        return "", {}, "packer.build.yml templates must be a non-empty mapping"

    requested = str(inputs.get("template_key") or "").strip()
    if not requested:
        requested = str(pack_cfg.get("default_template_key") or "").strip()
    if not requested:
        requested = str(next(iter(templates.keys())))

    selected = templates.get(requested)
    if not isinstance(selected, dict):
        keys = ", ".join(sorted([str(k) for k in templates.keys()]))
        return "", {}, f"template_key not found: {requested} (available: {keys})"

    return requested, selected, ""


def load_pack_config(path: Path) -> tuple[dict[str, Any], str]:
    if not path.exists():
        return {}, f"pack config not found: {path}"
    try:
        payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except Exception as exc:
        return {}, f"failed to parse pack config {path}: {exc}"
    if not isinstance(payload, dict):
        return {}, f"pack config must be a mapping: {path}"
    return payload, ""
