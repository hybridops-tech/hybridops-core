"""
purpose: Validate inputs for core/onprem/network-sdn module.
Architecture Decision: ADR-N/A (onprem network-sdn validator)
maintainer: HybridOps.Studio
"""

from __future__ import annotations

import ipaddress
import re
from typing import Any


def _require_non_empty_str(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be a non-empty string")
    return value.strip()


def _require_int_range(value: Any, field: str, min_value: int, max_value: int) -> int:
    if not isinstance(value, int) or value < min_value or value > max_value:
        raise ValueError(f"{field} must be an integer in [{min_value}, {max_value}]")
    return value


_SDN_ID_RE = re.compile(r"^[a-z][a-z0-9]{0,7}$")


def _require_sdn_id(value: Any, field: str) -> str:
    text = _require_non_empty_str(value, field)
    if not _SDN_ID_RE.match(text):
        raise ValueError(f"{field} must match ^[a-z][a-z0-9]{{0,7}}$ (lowercase, max 8 chars)")
    return text


def validate(inputs: dict[str, Any]) -> None:
    if not isinstance(inputs, dict):
        raise ValueError("inputs must be a mapping")

    strategy = str(inputs.get("zone_conflict_strategy") or "fail").strip().lower()
    if strategy not in ("fail", ""):
        raise ValueError("inputs.zone_conflict_strategy must be: fail")
    if "allow_non_shared_env" in inputs and not isinstance(inputs.get("allow_non_shared_env"), bool):
        raise ValueError("inputs.allow_non_shared_env must be a boolean when set")

    _require_sdn_id(inputs.get("zone_name"), "inputs.zone_name")
    _require_non_empty_str(inputs.get("zone_bridge"), "inputs.zone_bridge")
    _require_non_empty_str(inputs.get("uplink_interface"), "inputs.uplink_interface")
    _require_non_empty_str(inputs.get("dns_domain"), "inputs.dns_domain")
    _require_non_empty_str(inputs.get("dns_lease"), "inputs.dns_lease")
    if "host_reconcile_nonce" in inputs and not isinstance(inputs.get("host_reconcile_nonce"), str):
        raise ValueError("inputs.host_reconcile_nonce must be a string when set")

    post_apply_sdn_readiness = inputs.get("post_apply_sdn_readiness")
    if post_apply_sdn_readiness is not None and not isinstance(post_apply_sdn_readiness, (bool, dict)):
        raise ValueError("inputs.post_apply_sdn_readiness must be a boolean or mapping when set")
    if isinstance(post_apply_sdn_readiness, dict):
        for key in (
            "enabled",
            "required",
        ):
            if key in post_apply_sdn_readiness and not isinstance(post_apply_sdn_readiness.get(key), bool):
                raise ValueError(f"inputs.post_apply_sdn_readiness.{key} must be boolean")
        for key in ("timeout_s", "settle_wait_s", "proxmox_ssh_port"):
            if key in post_apply_sdn_readiness and not isinstance(post_apply_sdn_readiness.get(key), int):
                raise ValueError(f"inputs.post_apply_sdn_readiness.{key} must be an integer")
        for key in ("proxmox_ssh_user", "ssh_private_key_file"):
            if key in post_apply_sdn_readiness and not isinstance(post_apply_sdn_readiness.get(key), str):
                raise ValueError(f"inputs.post_apply_sdn_readiness.{key} must be a string")

    vnets = inputs.get("vnets")
    if not isinstance(vnets, dict) or not vnets:
        raise ValueError("inputs.vnets must be a non-empty mapping")

    seen_subnets: list[tuple[str, ipaddress.IPv4Network]] = []

    for vnet_key, vnet in vnets.items():
        vnet_name = _require_sdn_id(vnet_key, "inputs.vnets key")

        if not isinstance(vnet, dict):
            raise ValueError(f"inputs.vnets.{vnet_name} must be a mapping")

        _require_int_range(vnet.get("vlan_id"), f"inputs.vnets.{vnet_name}.vlan_id", 1, 4094)
        _require_non_empty_str(vnet.get("description"), f"inputs.vnets.{vnet_name}.description")

        subnets = vnet.get("subnets")
        if not isinstance(subnets, dict) or not subnets:
            raise ValueError(f"inputs.vnets.{vnet_name}.subnets must be a non-empty mapping")

        for subnet_key, subnet in subnets.items():
            subnet_name = _require_sdn_id(subnet_key, f"inputs.vnets.{vnet_name}.subnets key")
            if not isinstance(subnet, dict):
                raise ValueError(f"inputs.vnets.{vnet_name}.subnets.{subnet_name} must be a mapping")

            cidr = _require_non_empty_str(
                subnet.get("cidr"),
                f"inputs.vnets.{vnet_name}.subnets.{subnet_name}.cidr",
            )
            gateway = _require_non_empty_str(
                subnet.get("gateway"),
                f"inputs.vnets.{vnet_name}.subnets.{subnet_name}.gateway",
            )

            try:
                network = ipaddress.ip_network(cidr, strict=True)
            except Exception as exc:
                raise ValueError(
                    f"inputs.vnets.{vnet_name}.subnets.{subnet_name}.cidr is invalid: {exc}"
                ) from exc

            if not isinstance(network, ipaddress.IPv4Network):
                raise ValueError(
                    f"inputs.vnets.{vnet_name}.subnets.{subnet_name}.cidr must be IPv4"
                )

            try:
                gateway_ip = ipaddress.ip_address(gateway)
            except Exception as exc:
                raise ValueError(
                    f"inputs.vnets.{vnet_name}.subnets.{subnet_name}.gateway is invalid: {exc}"
                ) from exc

            if gateway_ip not in network:
                raise ValueError(
                    f"inputs.vnets.{vnet_name}.subnets.{subnet_name}.gateway must be inside {cidr}"
                )

            start = subnet.get("dhcp_range_start")
            end = subnet.get("dhcp_range_end")
            if (start and not end) or (end and not start):
                raise ValueError(
                    f"inputs.vnets.{vnet_name}.subnets.{subnet_name} requires dhcp_range_start and dhcp_range_end together"
                )

            if start and end:
                try:
                    start_ip = ipaddress.ip_address(str(start))
                    end_ip = ipaddress.ip_address(str(end))
                except Exception as exc:
                    raise ValueError(
                        f"inputs.vnets.{vnet_name}.subnets.{subnet_name} DHCP range is invalid: {exc}"
                    ) from exc
                if start_ip not in network or end_ip not in network:
                    raise ValueError(
                        f"inputs.vnets.{vnet_name}.subnets.{subnet_name} DHCP range must stay inside {cidr}"
                    )
                if int(start_ip) > int(end_ip):
                    raise ValueError(
                        f"inputs.vnets.{vnet_name}.subnets.{subnet_name}.dhcp_range_start must be <= dhcp_range_end"
                    )

            dns = subnet.get("dhcp_dns_server")
            if dns:
                try:
                    dns_ip = ipaddress.ip_address(str(dns))
                except Exception as exc:
                    raise ValueError(
                        f"inputs.vnets.{vnet_name}.subnets.{subnet_name}.dhcp_dns_server is invalid: {exc}"
                    ) from exc
                if not isinstance(dns_ip, ipaddress.IPv4Address):
                    raise ValueError(
                        f"inputs.vnets.{vnet_name}.subnets.{subnet_name}.dhcp_dns_server must be IPv4"
                    )

            seen_subnets.append((f"{vnet_name}.{subnet_name}", network))

    for i, (name_a, net_a) in enumerate(seen_subnets):
        for name_b, net_b in seen_subnets[i + 1 :]:
            if net_a.overlaps(net_b):
                raise ValueError(f"subnet overlap detected: {name_a} ({net_a}) <-> {name_b} ({net_b})")
