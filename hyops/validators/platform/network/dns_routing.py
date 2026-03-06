"""hyops.validators.platform.network.dns_routing

purpose: Validate inputs for platform/network/dns-routing module.
Architecture Decision: ADR-N/A (dns-routing validator)
maintainer: HybridOps.Studio
"""

from __future__ import annotations

import ipaddress
import re
from urllib.parse import urlparse
from typing import Any


_FQDN_RE = re.compile(r"^(?=.{1,253}$)([A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?)(\.[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?)*\.?$")


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


def _validate_inventory(data: dict[str, Any]) -> None:
    inventory_groups = data.get("inventory_groups")
    inventory_state_ref = data.get("inventory_state_ref")
    inventory_vm_groups = data.get("inventory_vm_groups")

    if isinstance(inventory_groups, dict) and inventory_groups:
        group = inventory_groups.get("edge_control")
        if not isinstance(group, list) or not group:
            raise ValueError("inputs.inventory_groups must include group 'edge_control' with at least one host")
        for idx, item in enumerate(group, start=1):
            if not isinstance(item, dict):
                raise ValueError(f"inputs.inventory_groups.edge_control[{idx}] must be a mapping")
            _require_non_empty_str(item.get("name"), f"inputs.inventory_groups.edge_control[{idx}].name")
            _require_non_empty_str(
                item.get("host") or item.get("ansible_host"),
                f"inputs.inventory_groups.edge_control[{idx}].host",
            )
        return

    if not isinstance(inventory_state_ref, str) or not inventory_state_ref.strip():
        raise ValueError(
            "inputs.inventory_state_ref is required when inputs.inventory_groups is empty "
            "(recommended: org/hetzner/shared-control-host#edge_control_host)"
        )
    if not isinstance(inventory_vm_groups, dict) or not inventory_vm_groups:
        raise ValueError(
            "inputs.inventory_vm_groups must be a non-empty mapping when inputs.inventory_state_ref is set"
        )
    edge_control = inventory_vm_groups.get("edge_control")
    if not isinstance(edge_control, list) or not edge_control:
        raise ValueError("inputs.inventory_vm_groups must include key 'edge_control' with at least one VM key")
    for idx, item in enumerate(edge_control, start=1):
        _require_non_empty_str(item, f"inputs.inventory_vm_groups.edge_control[{idx}]")


def _validate_targets(record_type: str, targets: Any, field: str) -> list[str]:
    if not isinstance(targets, list) or not targets:
        raise ValueError(f"{field} must be a non-empty list")
    out: list[str] = []
    for idx, item in enumerate(targets, start=1):
        token = _require_non_empty_str(item, f"{field}[{idx}]")
        if record_type == "A":
            try:
                ip = ipaddress.ip_address(token)
            except Exception as exc:
                raise ValueError(f"{field}[{idx}] must be a valid IPv4 address for A records") from exc
            if ip.version != 4:
                raise ValueError(f"{field}[{idx}] must be a valid IPv4 address for A records")
        elif record_type == "AAAA":
            try:
                ip = ipaddress.ip_address(token)
            except Exception as exc:
                raise ValueError(f"{field}[{idx}] must be a valid IPv6 address for AAAA records") from exc
            if ip.version != 6:
                raise ValueError(f"{field}[{idx}] must be a valid IPv6 address for AAAA records")
        elif record_type == "CNAME":
            if not _FQDN_RE.fullmatch(token):
                raise ValueError(f"{field}[{idx}] must be a valid hostname for CNAME records")
        out.append(token)
    return out


def _require_http_url(value: Any, field: str) -> str:
    token = _require_non_empty_str(value, field)
    parsed = urlparse(token)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError(f"{field} must be a valid http or https URL")
    return token


def _require_env_var_name(value: Any, field: str) -> str:
    token = _require_non_empty_str(value, field)
    if not re.fullmatch(r"[A-Z_][A-Z0-9_]*", token):
        raise ValueError(f"{field} must be a valid environment variable name")
    return token


def validate(inputs: dict[str, Any]) -> None:
    data = inputs or {}
    if not isinstance(data, dict):
        raise ValueError("inputs must be a mapping")

    _validate_inventory(data)

    _require_non_empty_str(data.get("target_user"), "inputs.target_user")
    if data.get("target_port") is not None:
        _require_port(data.get("target_port"), "inputs.target_port")
    if data.get("become") is not None and not isinstance(data.get("become"), bool):
        raise ValueError("inputs.become must be a boolean when set")
    if data.get("become_user") is not None:
        _require_non_empty_str(data.get("become_user"), "inputs.become_user")

    _require_non_empty_str(data.get("dns_role_fqcn"), "inputs.dns_role_fqcn")
    state = _require_non_empty_str(data.get("dns_state"), "inputs.dns_state").lower()
    if state not in {"present", "absent"}:
        raise ValueError("inputs.dns_state must be 'present' or 'absent'")
    if state == "absent":
        return

    provider = _require_non_empty_str(data.get("provider"), "inputs.provider")
    if "REPLACE_" in provider.upper():
        raise ValueError("inputs.provider contains placeholder token")

    if data.get("endpoint_state_ref") is not None and str(data.get("endpoint_state_ref")).strip():
        _require_non_empty_str(data.get("endpoint_state_ref"), "inputs.endpoint_state_ref")
    if data.get("endpoint_fqdn_output_key") is not None and str(data.get("endpoint_fqdn_output_key")).strip():
        _require_non_empty_str(data.get("endpoint_fqdn_output_key"), "inputs.endpoint_fqdn_output_key")
    if data.get("endpoint_target_output_key") is not None and str(data.get("endpoint_target_output_key")).strip():
        _require_non_empty_str(data.get("endpoint_target_output_key"), "inputs.endpoint_target_output_key")

    zone = _require_non_empty_str(data.get("zone"), "inputs.zone")
    if not _FQDN_RE.fullmatch(zone):
        raise ValueError("inputs.zone must be a valid DNS zone")

    fqdn = _require_non_empty_str(data.get("record_fqdn"), "inputs.record_fqdn")
    if not _FQDN_RE.fullmatch(fqdn):
        raise ValueError("inputs.record_fqdn must be a valid FQDN")

    record_type = _require_non_empty_str(data.get("record_type"), "inputs.record_type").upper()
    if record_type not in {"A", "AAAA", "CNAME"}:
        raise ValueError("inputs.record_type must be one of: A, AAAA, CNAME")

    ttl = data.get("ttl")
    if isinstance(ttl, bool) or not isinstance(ttl, int):
        raise ValueError("inputs.ttl must be an integer")
    if ttl < 1 or ttl > 86400:
        raise ValueError("inputs.ttl must be between 1 and 86400")

    desired = _require_non_empty_str(data.get("desired"), "inputs.desired").lower()
    if desired not in {"primary", "secondary"}:
        raise ValueError("inputs.desired must be one of: primary, secondary")

    primary_targets = _validate_targets(record_type, data.get("primary_targets"), "inputs.primary_targets")
    secondary_targets = _validate_targets(record_type, data.get("secondary_targets"), "inputs.secondary_targets")
    if record_type == "CNAME":
        if len(primary_targets) != 1:
            raise ValueError("inputs.primary_targets must contain exactly one target for CNAME records")
        if len(secondary_targets) != 1:
            raise ValueError("inputs.secondary_targets must contain exactly one target for CNAME records")

    dry_run = data.get("dry_run")
    dns_apply = data.get("dns_apply")
    if not isinstance(dry_run, bool):
        raise ValueError("inputs.dry_run must be a boolean")
    if not isinstance(dns_apply, bool):
        raise ValueError("inputs.dns_apply must be a boolean")
    if not dry_run and not dns_apply:
        raise ValueError("inputs.dns_apply must be true when inputs.dry_run=false")

    provider_command = str(data.get("provider_command") or "").strip()
    if provider == "manual-command":
        if dns_apply and not provider_command:
            raise ValueError(
                "inputs.provider_command is required when inputs.dns_apply=true and inputs.provider=manual-command"
            )
        return

    if provider != "powerdns-api":
        raise ValueError("inputs.provider must be one of: manual-command, powerdns-api")

    if data.get("powerdns_state_ref") is not None and str(data.get("powerdns_state_ref")).strip():
        _require_non_empty_str(data.get("powerdns_state_ref"), "inputs.powerdns_state_ref")

    if not str(data.get("powerdns_state_ref") or "").strip():
        _require_http_url(data.get("powerdns_api_url"), "inputs.powerdns_api_url")
        _require_non_empty_str(data.get("powerdns_server_id"), "inputs.powerdns_server_id")
    elif str(data.get("powerdns_api_url") or "").strip():
        _require_http_url(data.get("powerdns_api_url"), "inputs.powerdns_api_url")
    if str(data.get("powerdns_server_id") or "").strip():
        _require_non_empty_str(data.get("powerdns_server_id"), "inputs.powerdns_server_id")
    if data.get("powerdns_zone_id") is not None and str(data.get("powerdns_zone_id")).strip():
        _require_non_empty_str(data.get("powerdns_zone_id"), "inputs.powerdns_zone_id")
    key_env = _require_env_var_name(data.get("powerdns_api_key_env"), "inputs.powerdns_api_key_env")
    if data.get("powerdns_validate_tls") is not None and not isinstance(data.get("powerdns_validate_tls"), bool):
        raise ValueError("inputs.powerdns_validate_tls must be a boolean")
    if data.get("powerdns_account") is not None and str(data.get("powerdns_account")).strip():
        _require_non_empty_str(data.get("powerdns_account"), "inputs.powerdns_account")
    if data.get("powerdns_comment") is not None and not isinstance(data.get("powerdns_comment"), str):
        raise ValueError("inputs.powerdns_comment must be a string")
    required_env = data.get("required_env") or []
    if dns_apply and key_env not in required_env:
        raise ValueError(
            f"inputs.required_env must include '{key_env}' when inputs.provider=powerdns-api and inputs.dns_apply=true"
        )
