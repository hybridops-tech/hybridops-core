"""hyops.validators.platform.onprem.netbox

purpose: Validate inputs for platform/onprem/netbox module.
Architecture Decision: ADR-N/A (onprem netbox validator)
maintainer: HybridOps.Tech
"""

from __future__ import annotations

import ipaddress
from typing import Any

from hyops.validators.common import (
    normalize_lifecycle_command,
    normalize_required_env,
    require_mapping,
    require_non_empty_str,
    require_port,
)


def validate(inputs: dict[str, Any]) -> None:
    data = require_mapping(inputs, "inputs")

    cmd = normalize_lifecycle_command(data)

    target_host = str(data.get("target_host") or "").strip()
    target_state_ref = str(data.get("target_state_ref") or "").strip()
    if target_host:
        # Explicit target host (advanced / manual workflow).
        require_non_empty_str(target_host, "inputs.target_host")
    else:
        # State-driven target host (recommended for blueprints).
        if not target_state_ref:
            raise ValueError(
                "inputs.target_host must be a non-empty string when inputs.target_state_ref is not set"
            )
        require_non_empty_str(data.get("target_vm_key"), "inputs.target_vm_key")

    if data.get("target_user") is not None:
        require_non_empty_str(data.get("target_user"), "inputs.target_user")

    if data.get("target_port") is not None:
        require_port(data.get("target_port"), "inputs.target_port")

    if data.get("ssh_private_key_file") is not None and str(data.get("ssh_private_key_file") or "").strip() != "":
        require_non_empty_str(data.get("ssh_private_key_file"), "inputs.ssh_private_key_file")

    if data.get("become") is not None and not isinstance(data.get("become"), bool):
        raise ValueError("inputs.become must be a boolean when set")

    if data.get("become_user") is not None:
        require_non_empty_str(data.get("become_user"), "inputs.become_user")

    # Destroy should be able to run with minimal inputs (no DB contract required).
    if cmd == "destroy":
        return

    if data.get("load_vault_env") is not None and not isinstance(data.get("load_vault_env"), bool):
        raise ValueError("inputs.load_vault_env must be a boolean when set")

    required_env = normalize_required_env(data.get("required_env"), "inputs.required_env")

    if data.get("netbox_http_host_port") is not None:
        require_port(data.get("netbox_http_host_port"), "inputs.netbox_http_host_port")

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
        db_host = require_non_empty_str(db_host_raw, "inputs.db_host")
    if data.get("db_port") is not None:
        require_port(data.get("db_port"), "inputs.db_port")

    require_non_empty_str(data.get("db_name"), "inputs.db_name")
    require_non_empty_str(data.get("db_user"), "inputs.db_user")

    # Best-effort validation: db_host is IP or DNS-like string.
    # If it's an IP, validate it parses.
    if db_host:
        try:
            _ = ipaddress.ip_address(db_host)
        except Exception:
            pass

    db_password_env = require_non_empty_str(data.get("db_password_env"), "inputs.db_password_env")
    secret_key_env = require_non_empty_str(data.get("secret_key_env"), "inputs.secret_key_env")
    superuser_password_env = require_non_empty_str(data.get("superuser_password_env"), "inputs.superuser_password_env")
    api_token_env = require_non_empty_str(data.get("api_token_env"), "inputs.api_token_env")
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
