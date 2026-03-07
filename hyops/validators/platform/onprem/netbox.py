"""hyops.validators.platform.onprem.netbox

purpose: Validate inputs for platform/onprem/netbox module.
Architecture Decision: ADR-N/A (onprem netbox validator)
maintainer: HybridOps.Studio
"""

from __future__ import annotations

import ipaddress
from typing import Any


def _require_mapping(value: Any, field: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"{field} must be a mapping")
    return value


def _require_non_empty_str(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be a non-empty string")
    return value.strip()


def _require_port(value: Any, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{field} must be an integer")
    if value < 1 or value > 65535:
        raise ValueError(f"{field} must be between 1 and 65535")
    return value


def _normalize_required_env(value: Any) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise ValueError("inputs.required_env must be a list when set")
    out: list[str] = []
    for idx, item in enumerate(value, start=1):
        out.append(_require_non_empty_str(item, f"inputs.required_env[{idx}]"))
    return out


def validate(inputs: dict[str, Any]) -> None:
    data = _require_mapping(inputs, "inputs")

    cmd = str(data.get("_hyops_lifecycle_command") or "").strip().lower()

    target_host = str(data.get("target_host") or "").strip()
    target_state_ref = str(data.get("target_state_ref") or "").strip()
    if target_host:
        # Explicit target host (advanced / manual workflow).
        _require_non_empty_str(target_host, "inputs.target_host")
    else:
        # State-driven target host (recommended for blueprints).
        if not target_state_ref:
            raise ValueError(
                "inputs.target_host must be a non-empty string when inputs.target_state_ref is not set"
            )
        _require_non_empty_str(data.get("target_vm_key"), "inputs.target_vm_key")

    if data.get("target_user") is not None:
        _require_non_empty_str(data.get("target_user"), "inputs.target_user")

    if data.get("target_port") is not None:
        _require_port(data.get("target_port"), "inputs.target_port")

    if data.get("ssh_private_key_file") is not None and str(data.get("ssh_private_key_file") or "").strip() != "":
        _require_non_empty_str(data.get("ssh_private_key_file"), "inputs.ssh_private_key_file")

    if data.get("become") is not None and not isinstance(data.get("become"), bool):
        raise ValueError("inputs.become must be a boolean when set")

    if data.get("become_user") is not None:
        _require_non_empty_str(data.get("become_user"), "inputs.become_user")

    # Destroy should be able to run with minimal inputs (no DB contract required).
    if cmd == "destroy":
        return

    if data.get("load_vault_env") is not None and not isinstance(data.get("load_vault_env"), bool):
        raise ValueError("inputs.load_vault_env must be a boolean when set")

    required_env = _normalize_required_env(data.get("required_env"))

    if data.get("netbox_http_host_port") is not None:
        _require_port(data.get("netbox_http_host_port"), "inputs.netbox_http_host_port")

    if data.get("install_docker_engine") is not None and not isinstance(data.get("install_docker_engine"), bool):
        raise ValueError("inputs.install_docker_engine must be a boolean when set")

    allow_legacy_pgcore = data.get("allow_legacy_pgcore")
    if allow_legacy_pgcore is not None and not isinstance(allow_legacy_pgcore, bool):
        raise ValueError("inputs.allow_legacy_pgcore must be a boolean when set")
    allow_legacy_pgcore_bool = bool(allow_legacy_pgcore) if allow_legacy_pgcore is not None else False

    # DB contract (fail-fast)
    db_state_ref = str(data.get("db_state_ref") or "").strip()
    if db_state_ref.lower() == "platform/onprem/postgresql-core" and not allow_legacy_pgcore_bool:
        raise ValueError(
            "inputs.db_state_ref=platform/onprem/postgresql-core is deprecated for NetBox. "
            "Use inputs.db_state_ref=platform/postgresql-ha. "
            "For temporary rollback only, set inputs.allow_legacy_pgcore=true explicitly."
        )
    if allow_legacy_pgcore_bool and db_state_ref.lower() != "platform/onprem/postgresql-core":
        raise ValueError(
            "inputs.allow_legacy_pgcore=true is only valid when "
            "inputs.db_state_ref=platform/onprem/postgresql-core"
        )
    db_host_raw = str(data.get("db_host") or "").strip()
    if not db_host_raw and not db_state_ref:
        raise ValueError(
            "inputs.db_host must be a non-empty string when inputs.db_state_ref is not set"
        )

    db_host = db_host_raw
    if db_host_raw:
        db_host = _require_non_empty_str(db_host_raw, "inputs.db_host")
    if data.get("db_port") is not None:
        _require_port(data.get("db_port"), "inputs.db_port")

    _require_non_empty_str(data.get("db_name"), "inputs.db_name")
    _require_non_empty_str(data.get("db_user"), "inputs.db_user")

    # Best-effort validation: db_host is IP or DNS-like string.
    # If it's an IP, validate it parses.
    if db_host:
        try:
            _ = ipaddress.ip_address(db_host)
        except Exception:
            pass

    db_password_env = _require_non_empty_str(data.get("db_password_env"), "inputs.db_password_env")
    secret_key_env = _require_non_empty_str(data.get("secret_key_env"), "inputs.secret_key_env")
    superuser_password_env = _require_non_empty_str(data.get("superuser_password_env"), "inputs.superuser_password_env")
    api_token_env = _require_non_empty_str(data.get("api_token_env"), "inputs.api_token_env")
    if api_token_env != "NETBOX_API_TOKEN":
        raise ValueError("inputs.api_token_env must be NETBOX_API_TOKEN (standard HyOps NetBox integration contract)")

    missing_required_env = [
        k
        for k in (db_password_env, secret_key_env, superuser_password_env, api_token_env)
        if k not in required_env
    ]
    if missing_required_env:
        missing = ", ".join(missing_required_env)
        raise ValueError(
            f"inputs.required_env must include: {missing} "
            f"(required because inputs.*_env references them)"
        )
