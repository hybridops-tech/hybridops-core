"""
purpose: Shared input validation helpers for on-prem Proxmox VM modules.
Architecture Decision: ADR-N/A (onprem proxmox vm validators)
maintainer: HybridOps.Studio
"""

from __future__ import annotations

import ipaddress
import re
from typing import Any


_VM_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,62}$")
_MAC_RE = re.compile(r"^[0-9a-fA-F]{2}(?::[0-9a-fA-F]{2}){5}$")


def _require_mapping(value: Any, field: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"{field} must be a mapping")
    return value


def _require_non_empty_str(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be a non-empty string")
    return value.strip()


def _require_positive_int(value: Any, field: str) -> int:
    if not isinstance(value, int) or value <= 0:
        raise ValueError(f"{field} must be a positive integer")
    return value


def _require_str_list(value: Any, field: str) -> list[str]:
    if not isinstance(value, list):
        raise ValueError(f"{field} must be a list")
    out: list[str] = []
    for idx, item in enumerate(value, start=1):
        if not isinstance(item, str) or not item.strip():
            raise ValueError(f"{field}[{idx}] must be a non-empty string")
        out.append(item.strip())
    return out


def _require_vm_name(value: Any, field: str) -> str:
    vm_name = _require_non_empty_str(value, field).lower()
    if not _VM_NAME_RE.fullmatch(vm_name):
        raise ValueError(f"{field} must match ^[a-z0-9][a-z0-9-]{{0,62}}$")
    return vm_name


def _validate_require_ipam(data: dict[str, Any]) -> None:
    raw_require = data.get("require_ipam")
    if raw_require is None:
        return
    if not isinstance(raw_require, bool):
        raise ValueError("inputs.require_ipam must be a boolean when set")
    if not raw_require:
        return

    raw_addressing = data.get("addressing")
    if not isinstance(raw_addressing, dict):
        raise ValueError("inputs.addressing is required when inputs.require_ipam=true")

    mode = str(raw_addressing.get("mode") or "").strip().lower()
    if mode != "ipam":
        raise ValueError("inputs.addressing.mode must be ipam when inputs.require_ipam=true")

    raw_ipam = raw_addressing.get("ipam")
    if not isinstance(raw_ipam, dict):
        raise ValueError("inputs.addressing.ipam must be a mapping when inputs.require_ipam=true")

    provider = str(raw_ipam.get("provider") or "").strip().lower()
    if provider != "netbox":
        raise ValueError(
            "inputs.addressing.ipam.provider must be netbox when inputs.require_ipam=true"
        )


def _validate_allow_vm_set_replace(data: dict[str, Any]) -> None:
    raw = data.get("allow_vm_set_replace")
    if raw is None:
        return
    if not isinstance(raw, bool):
        raise ValueError("inputs.allow_vm_set_replace must be a boolean when set")


def _validate_interfaces(value: Any, field: str) -> None:
    if not isinstance(value, list) or not value:
        raise ValueError(f"{field} must be a non-empty list")

    for idx, item in enumerate(value, start=1):
        nic_field = f"{field}[{idx}]"
        nic = _require_mapping(item, nic_field)
        _require_non_empty_str(nic.get("bridge"), f"{nic_field}.bridge")

        mac = nic.get("mac_address")
        if mac is not None and str(mac).strip() != "":
            if not _MAC_RE.fullmatch(str(mac).strip()):
                raise ValueError(f"{nic_field}.mac_address must be a valid MAC address")

        ipv4 = nic.get("ipv4")
        if ipv4 is None:
            continue

        ipv4_map = _require_mapping(ipv4, f"{nic_field}.ipv4")
        address = _require_non_empty_str(ipv4_map.get("address"), f"{nic_field}.ipv4.address")
        gateway = str(ipv4_map.get("gateway") or "").strip()
        addr_token = address.lower()

        if addr_token == "dhcp":
            if gateway:
                raise ValueError(f"{nic_field}.ipv4.gateway must be empty when address is dhcp")
            continue

        try:
            iface = ipaddress.ip_interface(address)
        except Exception as exc:
            raise ValueError(f"{nic_field}.ipv4.address is invalid: {exc}") from exc
        if not isinstance(iface, ipaddress.IPv4Interface):
            raise ValueError(f"{nic_field}.ipv4.address must be IPv4")

        if idx == 1:
            if not gateway:
                raise ValueError(f"{nic_field}.ipv4.gateway is required for static primary NIC")
            try:
                gw_ip = ipaddress.ip_address(gateway)
            except Exception as exc:
                raise ValueError(f"{nic_field}.ipv4.gateway is invalid: {exc}") from exc
            if not isinstance(gw_ip, ipaddress.IPv4Address):
                raise ValueError(f"{nic_field}.ipv4.gateway must be IPv4")
            if gw_ip not in iface.network:
                raise ValueError(f"{nic_field}.ipv4.gateway must be within {iface.network}")
        else:
            if gateway:
                raise ValueError(f"{nic_field}.ipv4.gateway is only allowed on interfaces[1]")


def validate_single_vm_inputs(inputs: dict[str, Any]) -> None:
    data = _require_mapping(inputs, "inputs")
    _validate_require_ipam(data)
    _validate_allow_vm_set_replace(data)

    _require_vm_name(data.get("vm_name"), "inputs.vm_name")
    vm_id = data.get("vm_id")
    if vm_id is not None:
        _require_positive_int(vm_id, "inputs.vm_id")
    template_state_ref = str(data.get("template_state_ref") or "").strip()
    template_vm_id = data.get("template_vm_id")
    if template_vm_id is None:
        if not template_state_ref:
            raise ValueError(
                "inputs.template_state_ref is required (recommended: core/onprem/template-image); "
                "inputs.template_vm_id is only for explicit override"
            )
    else:
        _require_positive_int(template_vm_id, "inputs.template_vm_id")

    if data.get("template_state_ref") is not None and not isinstance(data.get("template_state_ref"), str):
        raise ValueError("inputs.template_state_ref must be a string when set")
    if data.get("template_key") is not None and not isinstance(data.get("template_key"), str):
        raise ValueError("inputs.template_key must be a string when set")
    if data.get("build_image") is not None and not isinstance(data.get("build_image"), bool):
        raise ValueError("inputs.build_image must be a boolean when set")

    _require_positive_int(data.get("cpu_cores"), "inputs.cpu_cores")
    _require_positive_int(data.get("memory_mb"), "inputs.memory_mb")
    _require_positive_int(data.get("disk_size_gb"), "inputs.disk_size_gb")

    vm_mac = _require_non_empty_str(data.get("vm_mac"), "inputs.vm_mac")
    if not _MAC_RE.fullmatch(vm_mac):
        raise ValueError("inputs.vm_mac must be a valid MAC address (AA:BB:CC:DD:EE:FF)")

    vm_ipv4_cidr = _require_non_empty_str(data.get("vm_ipv4_cidr"), "inputs.vm_ipv4_cidr")
    vm_gateway = _require_non_empty_str(data.get("vm_gateway"), "inputs.vm_gateway")

    try:
        vm_iface = ipaddress.ip_interface(vm_ipv4_cidr)
    except Exception as exc:
        raise ValueError(f"inputs.vm_ipv4_cidr is invalid: {exc}") from exc
    if not isinstance(vm_iface, ipaddress.IPv4Interface):
        raise ValueError("inputs.vm_ipv4_cidr must be an IPv4 interface CIDR")

    try:
        gw_ip = ipaddress.ip_address(vm_gateway)
    except Exception as exc:
        raise ValueError(f"inputs.vm_gateway is invalid: {exc}") from exc
    if not isinstance(gw_ip, ipaddress.IPv4Address):
        raise ValueError("inputs.vm_gateway must be IPv4")
    if gw_ip not in vm_iface.network:
        raise ValueError("inputs.vm_gateway must be within inputs.vm_ipv4_cidr network")

    _require_non_empty_str(data.get("cpu_type"), "inputs.cpu_type")
    _require_non_empty_str(data.get("dns_domain"), "inputs.dns_domain")

    dns_servers = _require_str_list(data.get("dns_servers"), "inputs.dns_servers")
    if not dns_servers:
        raise ValueError("inputs.dns_servers must contain at least one item")
    for idx, server in enumerate(dns_servers, start=1):
        try:
            parsed = ipaddress.ip_address(server)
        except Exception as exc:
            raise ValueError(f"inputs.dns_servers[{idx}] is invalid: {exc}") from exc
        if not isinstance(parsed, ipaddress.IPv4Address):
            raise ValueError(f"inputs.dns_servers[{idx}] must be IPv4")

    tags = _require_str_list(data.get("tags"), "inputs.tags")
    if not tags:
        raise ValueError("inputs.tags must contain at least one tag")


def validate_vm_pool_inputs(inputs: dict[str, Any]) -> None:
    data = _require_mapping(inputs, "inputs")
    _validate_require_ipam(data)
    _validate_allow_vm_set_replace(data)

    template_state_ref = str(data.get("template_state_ref") or "").strip()
    template_vm_id = data.get("template_vm_id")
    if template_vm_id is None:
        if not template_state_ref:
            raise ValueError(
                "inputs.template_state_ref is required (recommended: core/onprem/template-image); "
                "inputs.template_vm_id is only for explicit override"
            )
    else:
        _require_positive_int(template_vm_id, "inputs.template_vm_id")

    if data.get("template_state_ref") is not None and not isinstance(data.get("template_state_ref"), str):
        raise ValueError("inputs.template_state_ref must be a string when set")
    if data.get("template_key") is not None and not isinstance(data.get("template_key"), str):
        raise ValueError("inputs.template_key must be a string when set")
    if data.get("build_image") is not None and not isinstance(data.get("build_image"), bool):
        raise ValueError("inputs.build_image must be a boolean when set")

    _require_positive_int(data.get("cpu_cores"), "inputs.cpu_cores")
    _require_positive_int(data.get("memory_mb"), "inputs.memory_mb")
    _require_positive_int(data.get("disk_size_gb"), "inputs.disk_size_gb")
    _require_non_empty_str(data.get("cpu_type"), "inputs.cpu_type")
    _require_non_empty_str(data.get("os_type"), "inputs.os_type")
    _require_non_empty_str(data.get("dns_domain"), "inputs.dns_domain")

    dns_servers = _require_str_list(data.get("dns_servers"), "inputs.dns_servers")
    if not dns_servers:
        raise ValueError("inputs.dns_servers must contain at least one item")
    for idx, server in enumerate(dns_servers, start=1):
        try:
            parsed = ipaddress.ip_address(server)
        except Exception as exc:
            raise ValueError(f"inputs.dns_servers[{idx}] is invalid: {exc}") from exc
        if not isinstance(parsed, ipaddress.IPv4Address):
            raise ValueError(f"inputs.dns_servers[{idx}] must be IPv4")

    tags = _require_str_list(data.get("tags"), "inputs.tags")
    if not tags:
        raise ValueError("inputs.tags must contain at least one tag")

    raw_vms = data.get("vms")
    vm_name = str(data.get("vm_name") or "").strip()
    if raw_vms is None:
        if not vm_name:
            raise ValueError("either inputs.vms (non-empty map) or inputs.vm_name is required")
        validate_single_vm_inputs(data)
        return

    if not isinstance(raw_vms, dict):
        raise ValueError("inputs.vms must be a mapping when set")
    if not raw_vms:
        if not vm_name:
            raise ValueError("either inputs.vms (non-empty map) or inputs.vm_name is required")
        validate_single_vm_inputs(data)
        return

    module_interfaces = data.get("interfaces")
    has_module_interfaces = isinstance(module_interfaces, list) and len(module_interfaces) > 0
    if has_module_interfaces:
        _validate_interfaces(module_interfaces, "inputs.interfaces")

    for vm_name_raw, vm_cfg_raw in raw_vms.items():
        vm_name = _require_vm_name(vm_name_raw, "inputs.vms.<name>")
        vm_cfg = _require_mapping(vm_cfg_raw, f"inputs.vms[{vm_name}]")

        role = vm_cfg.get("role")
        if role is not None:
            _require_non_empty_str(role, f"inputs.vms[{vm_name}].role")

        vm_id = vm_cfg.get("vm_id")
        if vm_id is not None:
            _require_positive_int(vm_id, f"inputs.vms[{vm_name}].vm_id")

        vm_interfaces = vm_cfg.get("interfaces")
        if vm_interfaces is not None:
            _validate_interfaces(vm_interfaces, f"inputs.vms[{vm_name}].interfaces")
        elif not has_module_interfaces:
            raise ValueError(
                f"inputs.vms[{vm_name}].interfaces is required when module-level inputs.interfaces is empty"
            )
