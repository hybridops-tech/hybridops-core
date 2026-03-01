"""hyops.validators.platform.network.wan_edge

purpose: Validate inputs for platform/network/wan-edge module.
Architecture Decision: ADR-N/A (network wan-edge validator)
maintainer: HybridOps.Studio
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
        out.append(_require_non_empty_str(item, f"{field}[{idx}]"))
    return out


def _require_cidr_list(value: Any, field: str) -> list[str]:
    if not isinstance(value, list) or not value:
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


def _validate_optional_cidr_list(value: Any, field: str) -> None:
    if value is None:
        return
    if not isinstance(value, list):
        raise ValueError(f"{field} must be a list when set")
    for idx, item in enumerate(value, start=1):
        token = _require_non_empty_str(item, f"{field}[{idx}]")
        try:
            ipaddress.ip_network(token, strict=False)
        except Exception as exc:
            raise ValueError(f"{field}[{idx}] must be a valid CIDR") from exc


def _validate_inventory(data: dict[str, Any], edge01_key: str, edge02_key: str) -> None:
    inventory_groups = data.get("inventory_groups")
    inventory_state_ref = data.get("inventory_state_ref")
    inventory_vm_groups = data.get("inventory_vm_groups")

    expected = {edge01_key, edge02_key}

    if isinstance(inventory_groups, dict) and inventory_groups:
        group = inventory_groups.get("wan_edge")
        if not isinstance(group, list) or not group:
            raise ValueError("inputs.inventory_groups must include group 'wan_edge' with at least one host")

        names: set[str] = set()
        for idx, item in enumerate(group, start=1):
            if not isinstance(item, dict):
                raise ValueError(f"inputs.inventory_groups.wan_edge[{idx}] must be a mapping")
            name = _require_non_empty_str(item.get("name"), f"inputs.inventory_groups.wan_edge[{idx}].name")
            _require_non_empty_str(item.get("host") or item.get("ansible_host"), f"inputs.inventory_groups.wan_edge[{idx}].host")
            names.add(name)

        missing = sorted([k for k in expected if k not in names])
        if missing:
            raise ValueError(
                "inputs.inventory_groups.wan_edge must include host names for edge keys: " + ", ".join(missing)
            )
        return

    if not isinstance(inventory_state_ref, str) or not inventory_state_ref.strip():
        raise ValueError(
            "inputs.inventory_state_ref is required when inputs.inventory_groups is empty "
            "(recommended: org/hetzner/wan-edge-foundation)"
        )

    if not isinstance(inventory_vm_groups, dict) or not inventory_vm_groups:
        raise ValueError(
            "inputs.inventory_vm_groups must be a non-empty mapping when inputs.inventory_state_ref is set"
        )

    wan_edge = inventory_vm_groups.get("wan_edge")
    if not isinstance(wan_edge, list) or not wan_edge:
        raise ValueError("inputs.inventory_vm_groups must include key 'wan_edge' with at least one VM key")

    keys = {str(item or "").strip() for item in wan_edge}
    if "" in keys:
        raise ValueError("inputs.inventory_vm_groups.wan_edge entries must be non-empty strings")

    missing = sorted([k for k in expected if k not in keys])
    if missing:
        raise ValueError(
            "inputs.inventory_vm_groups.wan_edge must include edge keys: " + ", ".join(missing)
        )


def validate(inputs: dict[str, Any]) -> None:
    data = inputs or {}
    if not isinstance(data, dict):
        raise ValueError("inputs must be a mapping")

    edge01_key = _require_non_empty_str(data.get("edge01_vm_key"), "inputs.edge01_vm_key")
    edge02_key = _require_non_empty_str(data.get("edge02_vm_key"), "inputs.edge02_vm_key")
    if edge01_key == edge02_key:
        raise ValueError("inputs.edge01_vm_key and inputs.edge02_vm_key must be different")

    _validate_inventory(data, edge01_key=edge01_key, edge02_key=edge02_key)

    # SSH defaults applied to every host.
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
    if data.get("become_user") is not None:
        _require_non_empty_str(data.get("become_user"), "inputs.become_user")

    if data.get("wan_pub_if") is not None and str(data.get("wan_pub_if") or "").strip() != "":
        token = _require_non_empty_str(data.get("wan_pub_if"), "inputs.wan_pub_if")
        if not _IFNAME_RE.fullmatch(token):
            raise ValueError("inputs.wan_pub_if must match ^[a-zA-Z0-9_.-]+$")

    _require_non_empty_str(data.get("wan_role_fqcn"), "inputs.wan_role_fqcn")
    wan_ipsec_psk_env = _require_non_empty_str(data.get("wan_ipsec_psk_env"), "inputs.wan_ipsec_psk_env")

    required_env = _normalize_required_env(data.get("required_env"), "inputs.required_env")
    if wan_ipsec_psk_env not in required_env:
        raise ValueError(
            f"inputs.required_env must include: {wan_ipsec_psk_env} (referenced by inputs.wan_ipsec_psk_env)"
        )

    _require_ipv4(data.get("edge01_public_local_ip"), "inputs.edge01_public_local_ip")
    _require_ipv4(data.get("edge02_public_local_ip"), "inputs.edge02_public_local_ip")
    _require_ipv4(data.get("edge01_public_peer_ip"), "inputs.edge01_public_peer_ip")
    _require_ipv4(data.get("edge02_public_peer_ip"), "inputs.edge02_public_peer_ip")

    _require_ipv4(data.get("edge01_inside_local_ip"), "inputs.edge01_inside_local_ip")
    _require_ipv4(data.get("edge01_inside_peer_ip"), "inputs.edge01_inside_peer_ip")
    _require_ipv4(data.get("edge02_inside_local_ip"), "inputs.edge02_inside_local_ip")
    _require_ipv4(data.get("edge02_inside_peer_ip"), "inputs.edge02_inside_peer_ip")

    if data.get("inside_prefix_len") is None:
        raise ValueError("inputs.inside_prefix_len is required")
    if isinstance(data.get("inside_prefix_len"), bool) or not isinstance(data.get("inside_prefix_len"), int):
        raise ValueError("inputs.inside_prefix_len must be an integer")
    if int(data.get("inside_prefix_len")) != 30:
        raise ValueError("inputs.inside_prefix_len must be 30 (GCP HA VPN tunnel CIDR contract)")

    _require_non_empty_str(data.get("edge01_tunnel_name"), "inputs.edge01_tunnel_name")
    _require_non_empty_str(data.get("edge02_tunnel_name"), "inputs.edge02_tunnel_name")

    edge01_ifname = _require_non_empty_str(data.get("edge01_tunnel_ifname"), "inputs.edge01_tunnel_ifname")
    edge02_ifname = _require_non_empty_str(data.get("edge02_tunnel_ifname"), "inputs.edge02_tunnel_ifname")
    for token, field in ((edge01_ifname, "inputs.edge01_tunnel_ifname"), (edge02_ifname, "inputs.edge02_tunnel_ifname")):
        if not _IFNAME_RE.fullmatch(token):
            raise ValueError(f"{field} must match ^[a-zA-Z0-9_.-]+$")

    if data.get("edge01_tunnel_key") is None:
        raise ValueError("inputs.edge01_tunnel_key is required")
    if data.get("edge02_tunnel_key") is None:
        raise ValueError("inputs.edge02_tunnel_key is required")
    if isinstance(data.get("edge01_tunnel_key"), bool) or not isinstance(data.get("edge01_tunnel_key"), int):
        raise ValueError("inputs.edge01_tunnel_key must be an integer")
    if isinstance(data.get("edge02_tunnel_key"), bool) or not isinstance(data.get("edge02_tunnel_key"), int):
        raise ValueError("inputs.edge02_tunnel_key must be an integer")
    if int(data.get("edge01_tunnel_key")) < 1 or int(data.get("edge02_tunnel_key")) < 1:
        raise ValueError("inputs.edge01_tunnel_key and inputs.edge02_tunnel_key must be >= 1")

    _require_ipv4(data.get("edge01_router_id"), "inputs.edge01_router_id")
    _require_ipv4(data.get("edge02_router_id"), "inputs.edge02_router_id")

    _validate_optional_cidr_list(data.get("edge01_loopbacks"), "inputs.edge01_loopbacks")
    _validate_optional_cidr_list(data.get("edge02_loopbacks"), "inputs.edge02_loopbacks")

    _require_asn(data.get("wan_bgp_local_as"), "inputs.wan_bgp_local_as")
    _require_asn(data.get("wan_bgp_peer_as"), "inputs.wan_bgp_peer_as")

    _require_cidr_list(data.get("advertise_prefixes"), "inputs.advertise_prefixes")
    _require_cidr_list(data.get("import_allow_prefixes"), "inputs.import_allow_prefixes")
    _require_cidr_list(data.get("export_allow_prefixes"), "inputs.export_allow_prefixes")

    wan_ipsec = data.get("wan_ipsec")
    if wan_ipsec is not None and not isinstance(wan_ipsec, dict):
        raise ValueError("inputs.wan_ipsec must be a mapping when set")

    wan_host_overrides = data.get("wan_host_overrides")
    if wan_host_overrides is not None and not isinstance(wan_host_overrides, dict):
        raise ValueError("inputs.wan_host_overrides must be a mapping when set")

    if isinstance(wan_host_overrides, dict):
        for host_key, host_cfg in wan_host_overrides.items():
            key = str(host_key or "").strip()
            if not key:
                raise ValueError("inputs.wan_host_overrides keys must be non-empty strings")
            if not isinstance(host_cfg, dict):
                raise ValueError(f"inputs.wan_host_overrides[{key!r}] must be a mapping")
