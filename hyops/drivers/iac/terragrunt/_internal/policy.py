"""Terragrunt driver policy/requirements helpers (internal)."""

from __future__ import annotations

from pathlib import Path
from typing import Any
import re

from hyops.runtime.coerce import as_bool, as_int
from hyops.runtime.credentials import parse_tfvars, provider_env_key


_CRED_TOKEN_RE = re.compile(r"^[a-z0-9](?:[a-z0-9._-]*[a-z0-9])?$")


def resolve_profile_policy(profile: dict[str, Any]) -> tuple[dict[str, Any], str]:
    defaults = {
        "command_timeout_s": 0,
        "retries": 0,
        "redact": True,
        "min_free_disk_mb": 256,
    }
    out = {
        "defaults": dict(defaults),
        "naming": {},
        "workspace": {},
        "tool_versions": {},
        "constraints": {},
    }

    raw_policy = profile.get("policy")
    if raw_policy is None:
        return out, ""
    if not isinstance(raw_policy, dict):
        return out, "profile.policy must be a mapping"

    allowed_policy = {"defaults", "naming", "workspace", "tool_versions", "constraints"}
    unknown_policy = sorted([str(k) for k in raw_policy.keys() if str(k) not in allowed_policy])
    if unknown_policy:
        return out, f"profile.policy has unknown keys: {', '.join(unknown_policy)}"

    raw_defaults = raw_policy.get("defaults") or {}
    if raw_defaults and not isinstance(raw_defaults, dict):
        return out, "profile.policy.defaults must be a mapping"
    if isinstance(raw_defaults, dict):
        allowed_defaults = {"command_timeout_s", "retries", "redact", "min_free_disk_mb"}
        unknown_defaults = sorted(
            [str(k) for k in raw_defaults.keys() if str(k) not in allowed_defaults]
        )
        if unknown_defaults:
            return out, (
                "profile.policy.defaults has unknown keys: "
                + ", ".join(unknown_defaults)
            )

        try:
            timeout_s = as_int(raw_defaults.get("command_timeout_s"), default=defaults["command_timeout_s"])
        except Exception:
            return out, "profile.policy.defaults.command_timeout_s must be an integer when set"
        if timeout_s < 0:
            return out, "profile.policy.defaults.command_timeout_s must be >= 0"

        try:
            retries = as_int(raw_defaults.get("retries"), default=defaults["retries"])
        except Exception:
            return out, "profile.policy.defaults.retries must be an integer when set"
        if retries < 0:
            return out, "profile.policy.defaults.retries must be >= 0"

        redact = as_bool(raw_defaults.get("redact"), default=defaults["redact"])

        try:
            min_free_disk_mb = as_int(raw_defaults.get("min_free_disk_mb"), default=int(defaults["min_free_disk_mb"]))
        except Exception:
            return out, "profile.policy.defaults.min_free_disk_mb must be an integer when set"
        if min_free_disk_mb < 0:
            return out, "profile.policy.defaults.min_free_disk_mb must be >= 0"

        out["defaults"] = {
            "command_timeout_s": int(timeout_s),
            "retries": int(retries),
            "redact": bool(redact),
            "min_free_disk_mb": int(min_free_disk_mb),
        }

    for key in ("naming", "workspace", "constraints"):
        value = raw_policy.get(key) or {}
        if value and not isinstance(value, dict):
            return out, f"profile.policy.{key} must be a mapping"
        out[key] = value if isinstance(value, dict) else {}

    raw_tool_versions = raw_policy.get("tool_versions") or {}
    if raw_tool_versions and not isinstance(raw_tool_versions, dict):
        return out, "profile.policy.tool_versions must be a mapping"
    if isinstance(raw_tool_versions, dict):
        normalized_tool_versions: dict[str, str] = {}
        for key, value in raw_tool_versions.items():
            tool = str(key or "").strip()
            if not tool:
                return out, "profile.policy.tool_versions keys must be non-empty strings"
            spec = str(value or "").strip()
            if not spec:
                return out, f"profile.policy.tool_versions.{tool} must be a non-empty string"
            normalized_tool_versions[tool] = spec
        out["tool_versions"] = normalized_tool_versions

    return out, ""


def resolve_backend_mode(profile_policy: dict[str, Any]) -> tuple[str, str]:
    if not isinstance(profile_policy, dict):
        return "local", ""

    workspace = profile_policy.get("workspace")
    if workspace is None:
        return "local", ""
    if not isinstance(workspace, dict):
        return "local", "profile.policy.workspace must be a mapping"

    backend_mode = str(workspace.get("backend_mode") or "").strip().lower()
    if backend_mode:
        if backend_mode not in ("local", "cloud"):
            return "local", "profile.policy.workspace.backend_mode must be one of: local, cloud"
        return backend_mode, ""

    mode = str(workspace.get("mode") or "").strip().lower()
    if mode in ("remote", "agent"):
        return "cloud", ""
    return "local", ""


def normalize_required_credentials(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []

    out: list[str] = []
    seen: set[str] = set()

    for item in value:
        if not isinstance(item, str):
            continue

        token = item.strip().lower()
        if not token or not _CRED_TOKEN_RE.fullmatch(token):
            continue

        if token in seen:
            continue

        seen.add(token)
        out.append(token)

    return out


def resolve_required_credentials(request: dict[str, Any]) -> list[str]:
    requirements = request.get("requirements")
    if not isinstance(requirements, dict):
        return []

    return normalize_required_credentials(requirements.get("credentials"))


def resolve_credential_contracts(profile_policy: dict[str, Any]) -> tuple[dict[str, dict[str, list[str]]], str]:
    if not isinstance(profile_policy, dict):
        return {}, ""

    constraints = profile_policy.get("constraints")
    if constraints is None:
        return {}, ""
    if not isinstance(constraints, dict):
        return {}, "profile.policy.constraints must be a mapping"

    raw_contracts = constraints.get("credential_contracts")
    if raw_contracts is None:
        return {}, ""
    if not isinstance(raw_contracts, dict):
        return {}, "profile.policy.constraints.credential_contracts must be a mapping"

    out: dict[str, dict[str, list[str]]] = {}
    for provider, raw in raw_contracts.items():
        token = str(provider or "").strip().lower()
        if not token or not _CRED_TOKEN_RE.fullmatch(token):
            return {}, f"invalid credential contract provider: {provider!r}"
        if not isinstance(raw, dict):
            return {}, f"credential contract for {token} must be a mapping"

        raw_required = raw.get("required_tfvars") or []
        if raw_required and not isinstance(raw_required, list):
            return {}, f"credential contract {token}.required_tfvars must be a list"

        required_tfvars: list[str] = []
        seen: set[str] = set()
        for item in raw_required:
            key = str(item or "").strip()
            if not key:
                continue
            if key in seen:
                continue
            seen.add(key)
            required_tfvars.append(key)

        out[token] = {"required_tfvars": required_tfvars}

    return out, ""


def check_credential_contracts(
    *,
    required_credentials: list[str],
    credential_env: dict[str, str],
    contracts: dict[str, dict[str, list[str]]],
    env: dict[str, str],
) -> str:
    if not contracts:
        return ""

    errors: list[str] = []
    for provider in required_credentials:
        contract = contracts.get(provider)
        if not isinstance(contract, dict):
            continue

        required_tfvars = contract.get("required_tfvars") or []
        if not required_tfvars:
            continue

        provider_key = provider_env_key(provider)
        tfvars_env_key = f"HYOPS_{provider_key}_TFVARS"
        tfvars_path_raw = str(credential_env.get(tfvars_env_key) or env.get(tfvars_env_key) or "").strip()
        if not tfvars_path_raw:
            errors.append(
                f"{provider}: missing {tfvars_env_key} required by credential contract"
            )
            continue

        tfvars_path = Path(tfvars_path_raw).expanduser().resolve()
        tfvars = parse_tfvars(tfvars_path)
        missing: list[str] = []
        for key in required_tfvars:
            value = str(tfvars.get(key) or "").strip()
            if value:
                continue
            env_fallback = key.upper()
            if str(env.get(env_fallback) or "").strip():
                continue
            missing.append(key)

        if missing:
            errors.append(
                f"{provider}: credential contract missing keys in {tfvars_path}: {', '.join(sorted(missing))}"
            )

    if errors:
        return "; ".join(errors)
    return ""

