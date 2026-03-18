"""
purpose: Validate inputs for module org/hetzner/wan-edge-foundation.
Architecture Decision: ADR-0206 (module execution contract v1)
maintainer: HybridOps.Tech
"""

from __future__ import annotations

import ipaddress
import re
from typing import Any

from hyops.validators.common import (
    check_no_placeholder,
    opt_str,
    require_non_empty_str,
)
from hyops.validators.registry import ModuleValidationError


_SSH_PUBKEY_RE = re.compile(
    r"^(ssh-ed25519|ssh-rsa|ecdsa-sha2-nistp256|ecdsa-sha2-nistp384|ecdsa-sha2-nistp521|ssh-dss|"
    r"sk-ssh-ed25519@openssh\.com|sk-ecdsa-sha2-nistp256@openssh\.com|"
    r"sk-ssh-ed25519|sk-ecdsa-sha2-nistp256|sk-ecdsa-sha2-nistp384|sk-ecdsa-sha2-nistp521)\s+"
    r"([A-Za-z0-9+/=]+)(?:\s+.+)?$"
)


def _req_str(inputs: dict[str, Any], key: str) -> str:
    return check_no_placeholder(
        require_non_empty_str(inputs.get(key), f"inputs.{key}"),
        f"inputs.{key}",
    )


def _opt_str(inputs: dict[str, Any], key: str) -> str:
    v = opt_str(inputs.get(key), f"inputs.{key}")
    return check_no_placeholder(v, f"inputs.{key}") if v else v


def _opt_map(inputs: dict[str, Any], key: str) -> dict[str, Any]:
    v = inputs.get(key)
    if v is None:
        return {}
    if not isinstance(v, dict):
        raise ModuleValidationError(f"inputs.{key} must be a mapping when set")
    return v


def _req_cidr_list(inputs: dict[str, Any], key: str) -> list[str]:
    v = inputs.get(key)
    if not isinstance(v, list) or not v:
        raise ModuleValidationError(f"inputs.{key} must be a non-empty list")

    out: list[str] = []
    for idx, item in enumerate(v, start=1):
        if not isinstance(item, str) or not item.strip():
            raise ModuleValidationError(f"inputs.{key}[{idx}] must be a non-empty string")
        token = item.strip()
        try:
            ipaddress.ip_network(token, strict=False)
        except Exception as exc:
            raise ModuleValidationError(f"inputs.{key}[{idx}] must be a valid CIDR") from exc
        out.append(token)
    return out


def validate(inputs: dict[str, Any]) -> None:
    location = _req_str(inputs, "location")
    home_location = _req_str(inputs, "home_location")
    _ = location
    _ = home_location

    _req_str(inputs, "network_zone")
    _req_str(inputs, "server_type")
    _req_str(inputs, "image")

    _req_str(inputs, "edge01_name")
    _req_str(inputs, "edge02_name")

    _req_str(inputs, "ssh_key_name")
    ssh_public_key = _req_str(inputs, "ssh_public_key")
    if "CHANGE_ME" in ssh_public_key.upper():
        raise ModuleValidationError(
            "inputs.ssh_public_key contains placeholder text; provide a real SSH public key"
        )
    m = _SSH_PUBKEY_RE.fullmatch(ssh_public_key)
    if not m:
        raise ModuleValidationError(
            "inputs.ssh_public_key must be a valid SSH public key "
            "(e.g. starts with ssh-ed25519/ssh-rsa/ecdsa-...)"
        )
    key_material = m.group(2)
    if len(key_material) < 32:
        raise ModuleValidationError("inputs.ssh_public_key appears truncated; provide a full public key")

    _req_str(inputs, "firewall_name")
    _req_str(inputs, "floating_ip_name")
    floating_ip_type = _req_str(inputs, "floating_ip_type").lower()
    if floating_ip_type != "ipv4":
        raise ModuleValidationError("inputs.floating_ip_type currently supports only 'ipv4'")

    _req_str(inputs, "private_network_name")
    private_network_cidr = _req_str(inputs, "private_network_cidr")
    edge01_private_ip = _req_str(inputs, "edge01_private_ip")
    edge02_private_ip = _req_str(inputs, "edge02_private_ip")

    try:
        net = ipaddress.ip_network(private_network_cidr, strict=False)
    except Exception as exc:
        raise ModuleValidationError("inputs.private_network_cidr must be a valid CIDR") from exc

    if not isinstance(net, ipaddress.IPv4Network):
        raise ModuleValidationError("inputs.private_network_cidr must be an IPv4 CIDR")

    try:
        ip1 = ipaddress.ip_address(edge01_private_ip)
        ip2 = ipaddress.ip_address(edge02_private_ip)
    except Exception as exc:
        raise ModuleValidationError("inputs.edge01_private_ip and inputs.edge02_private_ip must be valid IPv4 addresses") from exc

    if not isinstance(ip1, ipaddress.IPv4Address) or not isinstance(ip2, ipaddress.IPv4Address):
        raise ModuleValidationError("inputs.edge01_private_ip and inputs.edge02_private_ip must be IPv4")

    if ip1 == ip2:
        raise ModuleValidationError("inputs.edge01_private_ip and inputs.edge02_private_ip must be different")

    if ip1 not in net or ip2 not in net:
        raise ModuleValidationError("inputs.edge01_private_ip and inputs.edge02_private_ip must be within inputs.private_network_cidr")

    assign = _req_str(inputs, "assign_floating_to").lower()
    if assign not in ("edge01", "edge02"):
        raise ModuleValidationError("inputs.assign_floating_to must be one of: edge01, edge02")

    _req_cidr_list(inputs, "ssh_source_cidrs")
    _req_cidr_list(inputs, "ipsec_source_cidrs")

    labels = _opt_map(inputs, "labels")
    for k, v in labels.items():
        if not isinstance(k, str) or not k.strip():
            raise ModuleValidationError("inputs.labels keys must be non-empty strings")
        if not isinstance(v, str):
            raise ModuleValidationError(f"inputs.labels[{k!r}] must be a string")
