"""hyops.validators.platform.network.vyos_edge_wan

purpose: Validate inputs for platform/network/vyos-edge-wan module.
Architecture Decision: ADR-N/A (vyos edge wan validator)
maintainer: HybridOps.Tech
"""

from __future__ import annotations

import ipaddress
import re
from typing import Any


_IFNAME_RE = re.compile(r"^[a-zA-Z0-9_.-]+$")


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


def _normalize_required_env(value: Any, field: str) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise ValueError(f"{field} must be a list when set")
    out: list[str] = []
    for idx, item in enumerate(value, start=1):
        out.append(_require_non_empty_str(item, f"{field}[{idx}]") )
    return out


def _require_cidr_list(value: Any, field: str, *, allow_empty: bool = False) -> list[str]:
    if not isinstance(value, list):
        raise ValueError(f"{field} must be a list")
    if not value and not allow_empty:
        raise ValueError(f"{field} must be a non-empty list")
    out: list[str] = []
    for idx, item in enumerate(value, start=1):
        token = _require_non_empty_str(item, f"{field}[{idx}]")
        try:
            ipaddress.ip_network(token, strict=False)
        except Exception as exc:
            raise ValueError(f"{field}[{idx}] must be a valid CIDR") from exc
        out.append(token)
    return out


def _validate_optional_ipv4(value: Any, field: str) -> None:
    if value is None:
        return
    token = str(value).strip()
    if token == "":
        return
    _require_ipv4(token, field)


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


def validate(inputs: dict[str, Any]) -> None:
    data = inputs or {}
    if not isinstance(data, dict):
        raise ValueError("inputs must be a mapping")

    _validate_inventory(data)

    _require_non_empty_str(data.get("target_user"), "inputs.target_user")
    if data.get("target_port") is not None:
        _require_port(data.get("target_port"), "inputs.target_port")

    if data.get("ssh_private_key_file") is not None and str(data.get("ssh_private_key_file") or "").strip() != "":
        _require_non_empty_str(data.get("ssh_private_key_file"), "inputs.ssh_private_key_file")

    if data.get("ssh_proxy_jump_host") is not None and str(data.get("ssh_proxy_jump_host") or "").strip() != "":
        _require_non_empty_str(data.get("ssh_proxy_jump_host"), "inputs.ssh_proxy_jump_host")
        if data.get("ssh_proxy_jump_user") is not None:
            _require_non_empty_str(data.get("ssh_proxy_jump_user"), "inputs.ssh_proxy_jump_user")
        if data.get("ssh_proxy_jump_port") is not None:
            _require_port(data.get("ssh_proxy_jump_port"), "inputs.ssh_proxy_jump_port")
    if data.get("ssh_proxy_jump_auto") is not None and not isinstance(data.get("ssh_proxy_jump_auto"), bool):
        raise ValueError("inputs.ssh_proxy_jump_auto must be a boolean when set")

    if data.get("become") is not None and not isinstance(data.get("become"), bool):
        raise ValueError("inputs.become must be a boolean when set")
    if data.get("become_user") is not None and str(data.get("become_user") or "").strip() != "":
        _require_non_empty_str(data.get("become_user"), "inputs.become_user")

    _require_non_empty_str(data.get("vyos_wan_role_fqcn"), "inputs.vyos_wan_role_fqcn")

    state = _require_non_empty_str(data.get("vyos_wan_state"), "inputs.vyos_wan_state").lower()
    if state not in {"present", "absent"}:
        raise ValueError("inputs.vyos_wan_state must be 'present' or 'absent'")

    wan_ipsec_psk_env = _require_non_empty_str(data.get("wan_ipsec_psk_env"), "inputs.wan_ipsec_psk_env")
    required_env = _normalize_required_env(data.get("required_env"), "inputs.required_env")
    if state == "present" and wan_ipsec_psk_env not in required_env:
        raise ValueError(
            f"inputs.required_env must include: {wan_ipsec_psk_env} (referenced by inputs.wan_ipsec_psk_env)"
        )

    _require_non_empty_str(data.get("vyos_ssh_user"), "inputs.vyos_ssh_user")
    if data.get("vyos_ssh_port") is not None:
        _require_port(data.get("vyos_ssh_port"), "inputs.vyos_ssh_port")

    if data.get("edge_ssh_connectivity_timeout_s") is not None:
        if isinstance(data.get("edge_ssh_connectivity_timeout_s"), bool) or not isinstance(data.get("edge_ssh_connectivity_timeout_s"), int):
            raise ValueError("inputs.edge_ssh_connectivity_timeout_s must be an integer")
        if int(data.get("edge_ssh_connectivity_timeout_s")) < 1 or int(data.get("edge_ssh_connectivity_timeout_s")) > 60:
            raise ValueError("inputs.edge_ssh_connectivity_timeout_s must be between 1 and 60")

    if data.get("edge_ssh_connectivity_wait_s") is not None:
        if isinstance(data.get("edge_ssh_connectivity_wait_s"), bool) or not isinstance(data.get("edge_ssh_connectivity_wait_s"), int):
            raise ValueError("inputs.edge_ssh_connectivity_wait_s must be an integer")
        if int(data.get("edge_ssh_connectivity_wait_s")) < 1 or int(data.get("edge_ssh_connectivity_wait_s")) > 900:
            raise ValueError("inputs.edge_ssh_connectivity_wait_s must be between 1 and 900")
    vyos_ssh_key_file = str(data.get("vyos_ssh_key_file") or "").strip()
    vyos_ssh_private_key_env = str(data.get("vyos_ssh_private_key_env") or "").strip()
    if not vyos_ssh_key_file and not vyos_ssh_private_key_env:
        raise ValueError(
            "one of inputs.vyos_ssh_key_file or inputs.vyos_ssh_private_key_env must be set "
            "for control-host -> VyOS authentication"
        )
    if vyos_ssh_key_file:
        _require_non_empty_str(vyos_ssh_key_file, "inputs.vyos_ssh_key_file")
    if vyos_ssh_private_key_env:
        _require_non_empty_str(vyos_ssh_private_key_env, "inputs.vyos_ssh_private_key_env")

    vyos_ssh_opts = data.get("vyos_ssh_opts")
    if vyos_ssh_opts is not None:
        if not isinstance(vyos_ssh_opts, list):
            raise ValueError("inputs.vyos_ssh_opts must be a list when set")
        for idx, item in enumerate(vyos_ssh_opts, start=1):
            _require_non_empty_str(item, f"inputs.vyos_ssh_opts[{idx}]")

    _require_non_empty_str(data.get("edge01_name"), "inputs.edge01_name")
    _require_non_empty_str(data.get("edge02_name"), "inputs.edge02_name")
    _validate_optional_ipv4(data.get("edge01_ssh_host"), "inputs.edge01_ssh_host")
    _validate_optional_ipv4(data.get("edge02_ssh_host"), "inputs.edge02_ssh_host")
    _validate_optional_ipv4(data.get("edge01_public_ip"), "inputs.edge01_public_ip")
    _validate_optional_ipv4(data.get("edge02_public_ip"), "inputs.edge02_public_ip")
    _validate_optional_ipv4(data.get("edge01_peer_public_ip"), "inputs.edge01_peer_public_ip")
    _validate_optional_ipv4(data.get("edge02_peer_public_ip"), "inputs.edge02_peer_public_ip")
    edge_ipsec_source_cidrs = _require_cidr_list(
        data.get("edge_ipsec_source_cidrs") or [],
        "inputs.edge_ipsec_source_cidrs",
        allow_empty=True,
    )

    for field in ("edge01_peer_public_ip", "edge02_peer_public_ip"):
        peer_ip_raw = data.get(field)
        if peer_ip_raw is None or str(peer_ip_raw).strip() == "":
            continue
        peer_ip = ipaddress.ip_address(_require_ipv4(peer_ip_raw, f"inputs.{field}"))
        if edge_ipsec_source_cidrs and not any(
            peer_ip in ipaddress.ip_network(cidr, strict=False)
            for cidr in edge_ipsec_source_cidrs
        ):
            raise ValueError(
                f"inputs.{field}={peer_ip} is not allowed by inputs.edge_ipsec_source_cidrs. "
                "Update org/hetzner/vyos-edge-foundation so the Hetzner firewall allows the current "
                "GCP HA VPN public peer IPs before rerunning platform/network/vyos-edge-wan."
            )

    _require_ipv4(data.get("edge01_inside_local_ip"), "inputs.edge01_inside_local_ip")
    _require_ipv4(data.get("edge01_inside_peer_ip"), "inputs.edge01_inside_peer_ip")
    _require_ipv4(data.get("edge02_inside_local_ip"), "inputs.edge02_inside_local_ip")
    _require_ipv4(data.get("edge02_inside_peer_ip"), "inputs.edge02_inside_peer_ip")
    _require_ipv4(data.get("edge01_router_id"), "inputs.edge01_router_id")
    _require_ipv4(data.get("edge02_router_id"), "inputs.edge02_router_id")

    edge01_ifname = _require_non_empty_str(data.get("edge01_tunnel_ifname"), "inputs.edge01_tunnel_ifname")
    edge02_ifname = _require_non_empty_str(data.get("edge02_tunnel_ifname"), "inputs.edge02_tunnel_ifname")
    for token, field in ((edge01_ifname, "inputs.edge01_tunnel_ifname"), (edge02_ifname, "inputs.edge02_tunnel_ifname")):
        if not _IFNAME_RE.fullmatch(token):
            raise ValueError(f"{field} must match ^[a-zA-Z0-9_.-]+$")

    _require_non_empty_str(data.get("edge01_tunnel_name"), "inputs.edge01_tunnel_name")
    _require_non_empty_str(data.get("edge02_tunnel_name"), "inputs.edge02_tunnel_name")

    if data.get("inside_prefix_len") is None:
        raise ValueError("inputs.inside_prefix_len is required")
    if isinstance(data.get("inside_prefix_len"), bool) or not isinstance(data.get("inside_prefix_len"), int):
        raise ValueError("inputs.inside_prefix_len must be an integer")
    if int(data.get("inside_prefix_len")) != 30:
        raise ValueError("inputs.inside_prefix_len must be 30 (GCP HA VPN tunnel CIDR contract)")

    _require_asn(data.get("local_asn"), "inputs.local_asn")
    _require_asn(data.get("peer_asn"), "inputs.peer_asn")

    _require_cidr_list(data.get("advertise_prefixes"), "inputs.advertise_prefixes", allow_empty=True)
    _require_cidr_list(data.get("import_allow_prefixes"), "inputs.import_allow_prefixes")

    _require_non_empty_str(data.get("ipsec_ike_group"), "inputs.ipsec_ike_group")
    _require_non_empty_str(data.get("ipsec_esp_group"), "inputs.ipsec_esp_group")
    _require_non_empty_str(data.get("bgp_export_prefix_list"), "inputs.bgp_export_prefix_list")
    _require_non_empty_str(data.get("bgp_import_prefix_list"), "inputs.bgp_import_prefix_list")
    _require_non_empty_str(data.get("bgp_export_route_map"), "inputs.bgp_export_route_map")
    _require_non_empty_str(data.get("bgp_import_route_map"), "inputs.bgp_import_route_map")

    if data.get("validate_post_apply") is not None and not isinstance(data.get("validate_post_apply"), bool):
        raise ValueError("inputs.validate_post_apply must be a boolean when set")

    if data.get("status_convergence_retries") is not None:
        if isinstance(data.get("status_convergence_retries"), bool) or not isinstance(data.get("status_convergence_retries"), int):
            raise ValueError("inputs.status_convergence_retries must be an integer")
        if int(data.get("status_convergence_retries")) < 1 or int(data.get("status_convergence_retries")) > 120:
            raise ValueError("inputs.status_convergence_retries must be between 1 and 120")

    if data.get("status_convergence_delay_s") is not None:
        if isinstance(data.get("status_convergence_delay_s"), bool) or not isinstance(data.get("status_convergence_delay_s"), int):
            raise ValueError("inputs.status_convergence_delay_s must be an integer")
        if int(data.get("status_convergence_delay_s")) < 1 or int(data.get("status_convergence_delay_s")) > 120:
            raise ValueError("inputs.status_convergence_delay_s must be between 1 and 120")

    if data.get("vyos_wan_no_log_sensitive") is not None and not isinstance(data.get("vyos_wan_no_log_sensitive"), bool):
        raise ValueError("inputs.vyos_wan_no_log_sensitive must be a boolean when set")
