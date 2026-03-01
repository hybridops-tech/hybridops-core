"""hyops.validators.platform.onprem.postgresql_dr_source

purpose: Validate inputs for platform/onprem/postgresql-dr-source module.
Architecture Decision: ADR-N/A (postgresql dr source validator)
maintainer: HybridOps.Studio
"""

from __future__ import annotations

import ipaddress
from typing import Any

from hyops.validators.common import normalize_required_env, require_mapping, require_non_empty_str, require_port


def _require_bool(value: Any, field: str) -> bool:
    if not isinstance(value, bool):
        raise ValueError(f"{field} must be a boolean")
    return value


def _require_int(value: Any, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{field} must be an integer")
    return value


def _validate_inventory_contract(data: dict[str, Any]) -> None:
    inventory_state_ref = str(data.get("inventory_state_ref") or "").strip()
    inventory_groups = data.get("inventory_groups")
    if inventory_state_ref:
        require_non_empty_str(inventory_state_ref, "inputs.inventory_state_ref")
    elif isinstance(inventory_groups, dict) and inventory_groups:
        return
    else:
        raise ValueError(
            "inputs.inventory_state_ref or inputs.inventory_groups is required "
            "(prefer state-driven inventory from platform/onprem/postgresql-ha)"
        )


def _validate_db_contract(data: dict[str, Any]) -> None:
    db_state_ref = str(data.get("db_state_ref") or "").strip()
    db_host = str(data.get("db_host") or "").strip()
    if db_state_ref:
        require_non_empty_str(db_state_ref, "inputs.db_state_ref")
    elif db_host:
        require_non_empty_str(db_host, "inputs.db_host")
    else:
        raise ValueError(
            "inputs.db_state_ref or inputs.db_host is required "
            "(prefer state-driven DB contract from platform/onprem/postgresql-ha)"
        )

    if data.get("db_port") is not None:
        require_port(data.get("db_port"), "inputs.db_port")

    if str(data.get("db_name") or "").strip():
        require_non_empty_str(data.get("db_name"), "inputs.db_name")
    if str(data.get("db_user") or "").strip():
        require_non_empty_str(data.get("db_user"), "inputs.db_user")
    if str(data.get("db_password_env") or "").strip():
        require_non_empty_str(data.get("db_password_env"), "inputs.db_password_env")
    if str(data.get("db_app_key") or "").strip():
        require_non_empty_str(data.get("db_app_key"), "inputs.db_app_key")


def _validate_cidrs(value: Any, field: str) -> None:
    if value is None:
        return
    if not isinstance(value, list):
        raise ValueError(f"{field} must be a list")
    for idx, item in enumerate(value, start=1):
        cidr = require_non_empty_str(item, f"{field}[{idx}]")
        try:
            ipaddress.ip_network(cidr, strict=False)
        except Exception as exc:
            raise ValueError(f"{field}[{idx}] must be a valid CIDR") from exc


def validate(inputs: dict[str, Any]) -> None:
    data = require_mapping(inputs, "inputs")
    lifecycle = str(data.get("_hyops_lifecycle_command") or "").strip().lower()

    _validate_inventory_contract(data)

    if data.get("target_user") is not None:
        require_non_empty_str(data.get("target_user"), "inputs.target_user")
    if data.get("target_port") is not None:
        require_port(data.get("target_port"), "inputs.target_port")
    if data.get("ssh_private_key_file") is not None and str(data.get("ssh_private_key_file") or "").strip():
        require_non_empty_str(data.get("ssh_private_key_file"), "inputs.ssh_private_key_file")
    if data.get("ssh_proxy_jump_auto") is not None:
        _require_bool(data.get("ssh_proxy_jump_auto"), "inputs.ssh_proxy_jump_auto")
    if data.get("ssh_proxy_jump_host") is not None and str(data.get("ssh_proxy_jump_host") or "").strip():
        require_non_empty_str(data.get("ssh_proxy_jump_host"), "inputs.ssh_proxy_jump_host")
    if data.get("ssh_proxy_jump_user") is not None:
        require_non_empty_str(data.get("ssh_proxy_jump_user"), "inputs.ssh_proxy_jump_user")
    if data.get("ssh_proxy_jump_port") is not None:
        require_port(data.get("ssh_proxy_jump_port"), "inputs.ssh_proxy_jump_port")
    if data.get("become") is not None:
        _require_bool(data.get("become"), "inputs.become")
    if data.get("become_user") is not None:
        require_non_empty_str(data.get("become_user"), "inputs.become_user")

    if data.get("inventory_requires_ipam") is not None:
        _require_bool(data.get("inventory_requires_ipam"), "inputs.inventory_requires_ipam")
    if data.get("connectivity_check") is not None:
        _require_bool(data.get("connectivity_check"), "inputs.connectivity_check")
    if data.get("connectivity_timeout_s") is not None:
        timeout = _require_int(data.get("connectivity_timeout_s"), "inputs.connectivity_timeout_s")
        if timeout < 1:
            raise ValueError("inputs.connectivity_timeout_s must be >= 1")
    if data.get("connectivity_wait_s") is not None:
        wait = _require_int(data.get("connectivity_wait_s"), "inputs.connectivity_wait_s")
        if wait < 0:
            raise ValueError("inputs.connectivity_wait_s must be >= 0")

    if data.get("load_vault_env") is not None:
        _require_bool(data.get("load_vault_env"), "inputs.load_vault_env")
    normalize_required_env(data.get("required_env"), "inputs.required_env")

    if lifecycle == "destroy":
        return

    mode = require_non_empty_str(data.get("apply_mode"), "inputs.apply_mode").lower()
    if mode != "assess":
        raise ValueError("inputs.apply_mode must be assess (v1)")

    dr_mode = require_non_empty_str(data.get("dr_mode"), "inputs.dr_mode").lower()
    if dr_mode not in ("managed-cloudsql", "export"):
        raise ValueError("inputs.dr_mode must be one of: managed-cloudsql, export")

    _validate_db_contract(data)

    version = _require_int(data.get("source_contract_version"), "inputs.source_contract_version")
    if version != 1:
        raise ValueError("inputs.source_contract_version must be 1 (v1)")

    _validate_cidrs(data.get("allowed_consumer_cidrs"), "inputs.allowed_consumer_cidrs")
