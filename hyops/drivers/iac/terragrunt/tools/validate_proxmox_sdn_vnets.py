#!/usr/bin/env python3
"""Validate Proxmox SDN vnets contract.

purpose: Fail fast on invalid custom SDN topology before Terragrunt driver actions.
maintainer: HybridOps.Tech
"""

from __future__ import annotations

import argparse
import ipaddress
import json
import os
from pathlib import Path


def _err(msg: str) -> int:
    print(f"ERR: {msg}")
    return 2


def _load_payload(args: argparse.Namespace) -> tuple[dict, str]:
    file_arg = str(getattr(args, "file", "") or "").strip()
    json_arg = str(getattr(args, "json", "") or "").strip()

    file_env = str(os.environ.get("HYOPS_PROXMOX_SDN_VNETS_FILE") or "").strip()
    json_env = str(os.environ.get("HYOPS_PROXMOX_SDN_VNETS_JSON") or "").strip()

    file_path = file_arg or file_env
    payload = json_arg or json_env

    if file_path:
        p = Path(file_path).expanduser().resolve()
        if not p.exists():
            raise ValueError(f"vnets file not found: {p}")
        payload = p.read_text(encoding="utf-8").strip()
        source = f"file:{p}"
    elif payload:
        source = "env/json"
    else:
        return {}, "default"

    if not payload:
        raise ValueError("vnets payload is empty")

    data = json.loads(payload)
    if not isinstance(data, dict):
        raise ValueError("vnets payload must be a JSON object")
    return data, source


def _validate(data: dict) -> None:
    if not data:
        raise ValueError("vnets object must not be empty")

    seen_subnets: list[tuple[str, ipaddress.IPv4Network]] = []

    for vnet_key, vnet in data.items():
        if not isinstance(vnet_key, str) or not vnet_key.strip():
            raise ValueError("vnet key must be a non-empty string")
        if not isinstance(vnet, dict):
            raise ValueError(f"{vnet_key}: vnet config must be an object")

        vlan_id = vnet.get("vlan_id")
        if not isinstance(vlan_id, int) or vlan_id < 1 or vlan_id > 4094:
            raise ValueError(f"{vnet_key}: vlan_id must be integer in [1, 4094]")

        desc = vnet.get("description")
        if not isinstance(desc, str) or not desc.strip():
            raise ValueError(f"{vnet_key}: description must be non-empty string")

        subnets = vnet.get("subnets")
        if not isinstance(subnets, dict) or not subnets:
            raise ValueError(f"{vnet_key}: subnets must be a non-empty object")

        for subnet_key, subnet in subnets.items():
            if not isinstance(subnet_key, str) or not subnet_key.strip():
                raise ValueError(f"{vnet_key}: subnet key must be non-empty string")
            if not isinstance(subnet, dict):
                raise ValueError(f"{vnet_key}.{subnet_key}: subnet config must be an object")

            cidr = subnet.get("cidr")
            gateway = subnet.get("gateway")
            if not isinstance(cidr, str) or not cidr.strip():
                raise ValueError(f"{vnet_key}.{subnet_key}: cidr must be non-empty string")
            if not isinstance(gateway, str) or not gateway.strip():
                raise ValueError(f"{vnet_key}.{subnet_key}: gateway must be non-empty string")

            try:
                network = ipaddress.ip_network(cidr, strict=True)
            except Exception as e:
                raise ValueError(f"{vnet_key}.{subnet_key}: invalid cidr '{cidr}': {e}")
            if not isinstance(network, ipaddress.IPv4Network):
                raise ValueError(f"{vnet_key}.{subnet_key}: only IPv4 cidr is supported")

            try:
                gw = ipaddress.ip_address(gateway)
            except Exception as e:
                raise ValueError(f"{vnet_key}.{subnet_key}: invalid gateway '{gateway}': {e}")
            if gw not in network:
                raise ValueError(f"{vnet_key}.{subnet_key}: gateway {gateway} is outside {cidr}")

            start = subnet.get("dhcp_range_start")
            end = subnet.get("dhcp_range_end")
            if (start and not end) or (end and not start):
                raise ValueError(f"{vnet_key}.{subnet_key}: dhcp_range_start and dhcp_range_end must be set together")
            if start and end:
                try:
                    start_ip = ipaddress.ip_address(str(start))
                    end_ip = ipaddress.ip_address(str(end))
                except Exception as e:
                    raise ValueError(f"{vnet_key}.{subnet_key}: invalid DHCP range: {e}")
                if start_ip not in network or end_ip not in network:
                    raise ValueError(f"{vnet_key}.{subnet_key}: DHCP range must stay within {cidr}")
                if int(start_ip) > int(end_ip):
                    raise ValueError(f"{vnet_key}.{subnet_key}: dhcp_range_start must be <= dhcp_range_end")

            dns = subnet.get("dhcp_dns_server")
            if dns:
                try:
                    dns_ip = ipaddress.ip_address(str(dns))
                except Exception as e:
                    raise ValueError(f"{vnet_key}.{subnet_key}: invalid dhcp_dns_server '{dns}': {e}")
                if not isinstance(dns_ip, ipaddress.IPv4Address):
                    raise ValueError(f"{vnet_key}.{subnet_key}: dhcp_dns_server must be IPv4")

            seen_subnets.append((f"{vnet_key}.{subnet_key}", network))

    for i in range(len(seen_subnets)):
        n1_name, n1 = seen_subnets[i]
        for j in range(i + 1, len(seen_subnets)):
            n2_name, n2 = seen_subnets[j]
            if n1.overlaps(n2):
                raise ValueError(f"subnet overlap detected: {n1_name} ({n1}) <-> {n2_name} ({n2})")


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="validate_proxmox_sdn_vnets",
        description="Validate custom Proxmox SDN VNet JSON contract.",
    )
    p.add_argument("--file", default="", help="Path to JSON file (overrides env).")
    p.add_argument("--json", default="", help="Inline JSON payload (overrides env).")
    p.add_argument("--strict-empty", action="store_true", help="Fail when no custom VNet payload is provided.")
    return p


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)

    try:
        data, source = _load_payload(args)
    except Exception as e:
        return _err(str(e))

    if not data:
        if args.strict_empty:
            return _err("no custom VNet payload provided")
        print("sdn-vnets: no custom payload provided; using stack defaults")
        return 0

    try:
        _validate(data)
    except Exception as e:
        return _err(str(e))

    print(f"sdn-vnets: validation passed ({source})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
