"""hyops.validators.platform.network.powerdns_authority

purpose: Validate inputs for platform/network/powerdns-authority module.
maintainer: HybridOps.Tech
"""

from __future__ import annotations

from typing import Any

from hyops.validators.common import (
    normalize_required_env,
    require_non_empty_str as _require_non_empty_str,
    require_port as _require_port,
)


def _validate_inventory(data: dict[str, Any]) -> None:
    inventory_groups = data.get("inventory_groups")
    inventory_state_ref = data.get("inventory_state_ref")
    inventory_vm_groups = data.get("inventory_vm_groups")

    if isinstance(inventory_groups, dict) and inventory_groups:
        group = inventory_groups.get("dns")
        if not isinstance(group, list) or not group:
            raise ValueError("inputs.inventory_groups must include group 'dns' with at least one host")
        for idx, item in enumerate(group, start=1):
            if not isinstance(item, dict):
                raise ValueError(f"inputs.inventory_groups.dns[{idx}] must be a mapping")
            _require_non_empty_str(item.get("name"), f"inputs.inventory_groups.dns[{idx}].name")
            _require_non_empty_str(
                item.get("host") or item.get("ansible_host"),
                f"inputs.inventory_groups.dns[{idx}].host",
            )
        return

    if not isinstance(inventory_state_ref, str) or not inventory_state_ref.strip():
        raise ValueError(
            "inputs.inventory_state_ref is required when inputs.inventory_groups is empty"
        )
    if not isinstance(inventory_vm_groups, dict) or not inventory_vm_groups:
        raise ValueError(
            "inputs.inventory_vm_groups must be a non-empty mapping when inputs.inventory_state_ref is set"
        )
    group = inventory_vm_groups.get("dns")
    if not isinstance(group, list) or not group:
        raise ValueError("inputs.inventory_vm_groups must include key 'dns' with at least one VM key")
    for idx, item in enumerate(group, start=1):
        _require_non_empty_str(item, f"inputs.inventory_vm_groups.dns[{idx}]")


def validate(inputs: dict[str, Any]) -> None:
    data = inputs or {}
    if not isinstance(data, dict):
        raise ValueError("inputs must be a mapping")

    _validate_inventory(data)
    _require_non_empty_str(data.get("target_user"), "inputs.target_user")
    if data.get("target_port") is not None:
        _require_port(data.get("target_port"), "inputs.target_port")

    _require_non_empty_str(data.get("powerdns_role_fqcn"), "inputs.powerdns_role_fqcn")
    state = _require_non_empty_str(data.get("powerdns_state"), "inputs.powerdns_state").lower()
    if state not in {"present", "absent"}:
        raise ValueError("inputs.powerdns_state must be 'present' or 'absent'")
    if state == "absent":
        return

    mode = _require_non_empty_str(data.get("powerdns_mode"), "inputs.powerdns_mode").lower()
    if mode not in {"primary", "secondary"}:
        raise ValueError("inputs.powerdns_mode must be 'primary' or 'secondary'")

    _require_non_empty_str(data.get("powerdns_root"), "inputs.powerdns_root")
    _require_non_empty_str(data.get("powerdns_compose_project"), "inputs.powerdns_compose_project")
    _require_non_empty_str(data.get("powerdns_image"), "inputs.powerdns_image")
    _require_non_empty_str(data.get("powerdns_api_key_env"), "inputs.powerdns_api_key_env")
    _require_non_empty_str(data.get("powerdns_api_bind_host"), "inputs.powerdns_api_bind_host")
    _require_non_empty_str(data.get("powerdns_dns_bind_host"), "inputs.powerdns_dns_bind_host")
    _require_non_empty_str(data.get("powerdns_default_ns"), "inputs.powerdns_default_ns")
    _require_non_empty_str(data.get("powerdns_soa_admin"), "inputs.powerdns_soa_admin")
    if data.get("powerdns_primary_state_ref") is not None and str(data.get("powerdns_primary_state_ref")).strip():
        _require_non_empty_str(data.get("powerdns_primary_state_ref"), "inputs.powerdns_primary_state_ref")

    _require_port(data.get("powerdns_api_port"), "inputs.powerdns_api_port")
    _require_port(data.get("powerdns_dns_port"), "inputs.powerdns_dns_port")

    required_env = normalize_required_env(data.get("required_env"), "inputs.required_env")

    if not isinstance(data.get("powerdns_api_enabled"), bool):
        raise ValueError("inputs.powerdns_api_enabled must be a boolean")
    if data.get("powerdns_api_enabled"):
        direct_key = str(data.get("powerdns_api_key") or "").strip()
        key_env = _require_non_empty_str(data.get("powerdns_api_key_env"), "inputs.powerdns_api_key_env")
        if not direct_key and key_env not in required_env:
            raise ValueError(
                f"inputs.required_env must include '{key_env}' when inputs.powerdns_api_key is empty"
            )

    for field in ("powerdns_api_allow_from", "powerdns_allow_axfr_ips", "powerdns_allow_notify_from"):
        value = data.get(field)
        if value is None:
            continue
        if not isinstance(value, list):
            raise ValueError(f"inputs.{field} must be a list when set")
        for idx, item in enumerate(value, start=1):
            _require_non_empty_str(item, f"inputs.{field}[{idx}]")

    zone_name = str(data.get("powerdns_zone_name") or "").strip()
    if zone_name:
        if "." not in zone_name:
            raise ValueError("inputs.powerdns_zone_name must look like a DNS zone (example: hyops.internal)")
        if mode == "secondary":
            primary_endpoint = str(data.get("powerdns_primary_endpoint") or "").strip()
            primary_state_ref = str(data.get("powerdns_primary_state_ref") or "").strip()
            if not primary_endpoint and not primary_state_ref:
                raise ValueError(
                    "inputs.powerdns_primary_endpoint or inputs.powerdns_primary_state_ref is required "
                    "when inputs.powerdns_mode=secondary and inputs.powerdns_zone_name is set"
                )
