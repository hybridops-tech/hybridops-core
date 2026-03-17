"""hyops.validators.platform.onprem.netbox_db_migrate

purpose: Validate inputs for platform/onprem/netbox-db-migrate module.
Architecture Decision: ADR-N/A (netbox db migration validator)
maintainer: HybridOps.Tech
"""

from __future__ import annotations

from typing import Any

from hyops.validators.common import normalize_required_env, require_mapping, require_non_empty_str, require_port


def _require_bool(value: Any, field: str) -> bool:
    if not isinstance(value, bool):
        raise ValueError(f"{field} must be a boolean")
    return value


def _validate_target_host_contract(data: dict[str, Any]) -> None:
    target_host = str(data.get("target_host") or "").strip()
    target_state_ref = str(data.get("target_state_ref") or "").strip()
    if target_host:
        require_non_empty_str(target_host, "inputs.target_host")
    elif target_state_ref:
        require_non_empty_str(data.get("target_vm_key"), "inputs.target_vm_key")
    else:
        raise ValueError("inputs.target_host must be set, or inputs.target_state_ref + inputs.target_vm_key must be set")


def _validate_db_endpoint_or_state(data: dict[str, Any], *, prefix: str) -> None:
    p = prefix
    if p and not p.endswith("_"):
        p = f"{p}_"
    state_ref = str(data.get(f"{p}db_state_ref") or "").strip()
    host = str(data.get(f"{p}db_host") or "").strip()
    if not state_ref and not host:
        raise ValueError(
            f"inputs.{p}db_state_ref or inputs.{p}db_host is required "
            f"(use state-driven DB contracts for {prefix.rstrip('_') or 'db'})"
        )
    if host:
        require_non_empty_str(host, f"inputs.{p}db_host")
    if data.get(f"{p}db_port") is not None:
        require_port(data.get(f"{p}db_port"), f"inputs.{p}db_port")
    if str(data.get(f"{p}db_name") or "").strip():
        require_non_empty_str(data.get(f"{p}db_name"), f"inputs.{p}db_name")
    if str(data.get(f"{p}db_user") or "").strip():
        require_non_empty_str(data.get(f"{p}db_user"), f"inputs.{p}db_user")
    if str(data.get(f"{p}db_password_env") or "").strip():
        require_non_empty_str(data.get(f"{p}db_password_env"), f"inputs.{p}db_password_env")


def validate(inputs: dict[str, Any]) -> None:
    data = require_mapping(inputs, "inputs")
    lifecycle = str(data.get("_hyops_lifecycle_command") or "").strip().lower()

    _validate_target_host_contract(data)
    if data.get("target_user") is not None:
        require_non_empty_str(data.get("target_user"), "inputs.target_user")
    if data.get("target_port") is not None:
        require_port(data.get("target_port"), "inputs.target_port")
    if data.get("ssh_private_key_file") is not None and str(data.get("ssh_private_key_file") or "").strip():
        require_non_empty_str(data.get("ssh_private_key_file"), "inputs.ssh_private_key_file")
    if data.get("become") is not None:
        _require_bool(data.get("become"), "inputs.become")
    if data.get("become_user") is not None:
        require_non_empty_str(data.get("become_user"), "inputs.become_user")

    # destroy support is intentionally omitted (one-time workflow module); validate only targeting contract
    if lifecycle == "destroy":
        return

    _validate_db_endpoint_or_state(data, prefix="source_")
    _validate_db_endpoint_or_state(data, prefix="target_")

    if data.get("load_vault_env") is not None:
        _require_bool(data.get("load_vault_env"), "inputs.load_vault_env")

    required_env = normalize_required_env(data.get("required_env"), "inputs.required_env")

    source_env = require_non_empty_str(data.get("source_db_password_env"), "inputs.source_db_password_env")
    target_env = require_non_empty_str(data.get("target_db_password_env"), "inputs.target_db_password_env")
    for env_key in sorted({source_env, target_env}):
        if env_key not in required_env:
            raise ValueError(
                f"inputs.required_env must include: {env_key} "
                f"(required because inputs.source/target_db_password_env references it)"
            )

    method = str(data.get("migration_method") or "pg_dump_restore").strip().lower()
    if method != "pg_dump_restore":
        raise ValueError("inputs.migration_method must be pg_dump_restore (v1)")

    for field in ("migration_confirm", "maintenance_confirm"):
        _require_bool(data.get(field), f"inputs.{field}")
        if not bool(data.get(field)):
            raise ValueError(f"inputs.{field} must be true (explicit confirmation required)")

    if data.get("target_replace_confirm") is not None:
        _require_bool(data.get("target_replace_confirm"), "inputs.target_replace_confirm")

    for field in (
        "quiesce_netbox",
        "start_netbox_after_migration",
        "install_postgresql_client",
        "validate_row_counts",
    ):
        if data.get(field) is not None:
            _require_bool(data.get(field), f"inputs.{field}")

    require_non_empty_str(data.get("dump_artifact_dir"), "inputs.dump_artifact_dir")
    require_non_empty_str(data.get("netbox_compose_dir"), "inputs.netbox_compose_dir")
    require_non_empty_str(data.get("netbox_compose_project"), "inputs.netbox_compose_project")

    svc = data.get("netbox_quiesce_services")
    if not isinstance(svc, list) or not svc:
        raise ValueError("inputs.netbox_quiesce_services must be a non-empty list")
    for idx, item in enumerate(svc, start=1):
        require_non_empty_str(item, f"inputs.netbox_quiesce_services[{idx}]")

