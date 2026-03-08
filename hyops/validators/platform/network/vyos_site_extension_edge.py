"""hyops.validators.platform.network.vyos_site_extension_edge

purpose: Validate inputs for platform/network/vyos-site-extension-edge module.
maintainer: HybridOps.Studio
"""

from __future__ import annotations

import ipaddress
import re
from typing import Any


_IFNAME_RE = re.compile(r"^[a-zA-Z0-9_.-]+$")
_HOST_RE = re.compile(r"^(?=.{1,253}$)([A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?)(\.[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?)*\.?$")


def _require_non_empty_str(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be a non-empty string")
    token = value.strip()
    marker = token.upper()
    if marker.startswith("CHANGE_ME") or "CHANGE_ME_" in marker:
        raise ValueError(f"{field} must not contain placeholder values (found {token!r})")
    return token


def _require_port(value: Any, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{field} must be an integer")
    if value < 1 or value > 65535:
        raise ValueError(f"{field} must be between 1 and 65535")
    return value


def _require_asn(value: Any, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{field} must be an integer")
    if value < 1 or value > 4294967294:
        raise ValueError(f"{field} must be in range 1..4294967294")
    return value


def _require_ipv4(value: Any, field: str) -> str:
    token = _require_non_empty_str(value, field)
    try:
        ip = ipaddress.ip_address(token)
    except Exception as exc:
        raise ValueError(f"{field} must be a valid IPv4 address") from exc
    if not isinstance(ip, ipaddress.IPv4Address):
        raise ValueError(f"{field} must be a valid IPv4 address")
    return token


def _require_endpoint(value: Any, field: str) -> str:
    token = _require_non_empty_str(value, field)
    try:
        ip = ipaddress.ip_address(token)
    except Exception:
        ip = None
    if isinstance(ip, ipaddress.IPv4Address):
        return token
    if _HOST_RE.fullmatch(token):
        return token
    raise ValueError(f"{field} must be a valid IPv4 address or hostname/FQDN")


def _require_str_list(value: Any, field: str, *, allow_empty: bool = False) -> list[str]:
    if not isinstance(value, list):
        raise ValueError(f"{field} must be a list")
    if not value and not allow_empty:
        raise ValueError(f"{field} must be a non-empty list")
    out: list[str] = []
    for idx, item in enumerate(value, start=1):
        out.append(_require_non_empty_str(item, f"{field}[{idx}]"))
    return out


def _require_cidr_list(value: Any, field: str, *, allow_empty: bool = False) -> list[str]:
    tokens = _require_str_list(value, field, allow_empty=allow_empty)
    for idx, token in enumerate(tokens, start=1):
        try:
            ipaddress.ip_network(token, strict=False)
        except Exception as exc:
            raise ValueError(f"{field}[{idx}] must be a valid CIDR") from exc
    return tokens


def _ipv4_in_cidrs(ip_token: str, cidrs: list[str]) -> bool:
    candidate = ipaddress.ip_address(ip_token)
    if not isinstance(candidate, ipaddress.IPv4Address):
        return False
    for cidr in cidrs:
        if candidate in ipaddress.ip_network(cidr, strict=False):
            return True
    return False


def _validate_inventory(data: dict[str, Any]) -> None:
    inventory_groups = data.get("inventory_groups")
    inventory_state_ref = data.get("inventory_state_ref")
    inventory_vm_groups = data.get("inventory_vm_groups")

    if isinstance(inventory_groups, dict) and inventory_groups:
        group = inventory_groups.get("edge_control")
        if not isinstance(group, list) or not group:
            raise ValueError("inputs.inventory_groups must include group 'edge_control' with at least one host")
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


def validate(inputs: dict[str, Any]) -> None:
    data = inputs or {}
    if not isinstance(data, dict):
        raise ValueError("inputs must be a mapping")

    _validate_inventory(data)
    _require_non_empty_str(data.get("target_user"), "inputs.target_user")
    if data.get("target_port") is not None:
        _require_port(data.get("target_port"), "inputs.target_port")

    required_env = _require_str_list(data.get("required_env"), "inputs.required_env")
    psk_env = _require_non_empty_str(data.get("site_extension_psk_env"), "inputs.site_extension_psk_env")
    if psk_env not in required_env:
        raise ValueError(
            f"inputs.required_env must include: {psk_env} (referenced by inputs.site_extension_psk_env)"
        )

    state = _require_non_empty_str(data.get("vyos_site_extension_state"), "inputs.vyos_site_extension_state").lower()
    if state not in {"present", "absent"}:
        raise ValueError("inputs.vyos_site_extension_state must be 'present' or 'absent'")

    _require_non_empty_str(data.get("vyos_site_extension_edge_role_fqcn"), "inputs.vyos_site_extension_edge_role_fqcn")
    _require_non_empty_str(data.get("vyos_ssh_user"), "inputs.vyos_ssh_user")
    if data.get("vyos_ssh_port") is not None:
        _require_port(data.get("vyos_ssh_port"), "inputs.vyos_ssh_port")

    key_file = str(data.get("vyos_ssh_key_file") or "").strip()
    key_env = str(data.get("vyos_ssh_private_key_env") or "").strip()
    if not key_file and not key_env:
        raise ValueError(
            "one of inputs.vyos_ssh_key_file or inputs.vyos_ssh_private_key_env must be set "
            "for control-host -> VyOS authentication"
        )

    _require_non_empty_str(data.get("edge01_name"), "inputs.edge01_name")
    _require_non_empty_str(data.get("edge02_name"), "inputs.edge02_name")
    _require_ipv4(data.get("edge01_ssh_host"), "inputs.edge01_ssh_host")
    _require_ipv4(data.get("edge02_ssh_host"), "inputs.edge02_ssh_host")
    _require_ipv4(data.get("edge01_public_ip"), "inputs.edge01_public_ip")
    _require_ipv4(data.get("edge02_public_ip"), "inputs.edge02_public_ip")

    onprem_peer_remote_address = _require_endpoint(data.get("onprem_peer_remote_address"), "inputs.onprem_peer_remote_address")
    if str(data.get("onprem_peer_id") or "").strip():
        _require_non_empty_str(data.get("onprem_peer_id"), "inputs.onprem_peer_id")

    edge_ipsec_source_cidrs = _require_cidr_list(
        data.get("edge_ipsec_source_cidrs"),
        "inputs.edge_ipsec_source_cidrs",
        allow_empty=True,
    )
    try:
        endpoint_ip = ipaddress.ip_address(onprem_peer_remote_address)
    except Exception:
        endpoint_ip = None
    if isinstance(endpoint_ip, ipaddress.IPv4Address) and edge_ipsec_source_cidrs:
        if not _ipv4_in_cidrs(onprem_peer_remote_address, edge_ipsec_source_cidrs):
            raise ValueError(
                "inputs.onprem_peer_remote_address is not allowed by the current Hetzner edge "
                "foundation IPsec firewall allowlist. Reapply org/hetzner/vyos-edge-foundation "
                "with inputs.ipsec_source_cidrs extended to include this on-prem peer endpoint."
            )

    _require_ipv4(data.get("edge01_inside_local_ip"), "inputs.edge01_inside_local_ip")
    _require_ipv4(data.get("edge01_inside_peer_ip"), "inputs.edge01_inside_peer_ip")
    _require_ipv4(data.get("edge02_inside_local_ip"), "inputs.edge02_inside_local_ip")
    _require_ipv4(data.get("edge02_inside_peer_ip"), "inputs.edge02_inside_peer_ip")
    _require_ipv4(data.get("edge01_router_id"), "inputs.edge01_router_id")
    _require_ipv4(data.get("edge02_router_id"), "inputs.edge02_router_id")

    for token, field in (
        (data.get("edge01_tunnel_ifname"), "inputs.edge01_tunnel_ifname"),
        (data.get("edge02_tunnel_ifname"), "inputs.edge02_tunnel_ifname"),
    ):
        if not _IFNAME_RE.fullmatch(_require_non_empty_str(token, field)):
            raise ValueError(f"{field} must match ^[a-zA-Z0-9_.-]+$")

    _require_non_empty_str(data.get("edge_bind_interface"), "inputs.edge_bind_interface")

    if data.get("inside_prefix_len") is None:
        raise ValueError("inputs.inside_prefix_len is required")
    if isinstance(data.get("inside_prefix_len"), bool) or not isinstance(data.get("inside_prefix_len"), int):
        raise ValueError("inputs.inside_prefix_len must be an integer")
    if int(data.get("inside_prefix_len")) != 30:
        raise ValueError("inputs.inside_prefix_len must be 30")

    _require_asn(data.get("local_asn"), "inputs.local_asn")
    _require_asn(data.get("peer_asn"), "inputs.peer_asn")
    _require_cidr_list(data.get("advertise_prefixes"), "inputs.advertise_prefixes", allow_empty=True)
    _require_cidr_list(data.get("import_allow_prefixes"), "inputs.import_allow_prefixes", allow_empty=True)

    _require_non_empty_str(data.get("ipsec_ike_group"), "inputs.ipsec_ike_group")
    _require_non_empty_str(data.get("ipsec_esp_group"), "inputs.ipsec_esp_group")
    _require_non_empty_str(data.get("bgp_export_prefix_list"), "inputs.bgp_export_prefix_list")
    _require_non_empty_str(data.get("bgp_import_prefix_list"), "inputs.bgp_import_prefix_list")
    _require_non_empty_str(data.get("bgp_export_route_map"), "inputs.bgp_export_route_map")
    _require_non_empty_str(data.get("bgp_import_route_map"), "inputs.bgp_import_route_map")

    if data.get("validate_post_apply") is not None and not isinstance(data.get("validate_post_apply"), bool):
        raise ValueError("inputs.validate_post_apply must be a boolean when set")
