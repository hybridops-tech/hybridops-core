"""
purpose: Validate inputs for module org/gcp/wan-vpn-to-edge.
Architecture Decision: ADR-0206 (module execution contract v1)
maintainer: HybridOps.Studio
"""

from __future__ import annotations

import ipaddress
import re
from typing import Any

from hyops.validators.registry import ModuleValidationError


_PROJECT_ID_RE = re.compile(r"^[a-z][a-z0-9-]{4,28}[a-z0-9]$")


def _req_str(inputs: dict[str, Any], key: str) -> str:
    v = inputs.get(key)
    if not isinstance(v, str) or not v.strip():
        raise ModuleValidationError(f"inputs.{key} must be a non-empty string")
    return v.strip()


def _req_ipv4(inputs: dict[str, Any], key: str) -> str:
    token = _req_str(inputs, key)
    try:
        ip = ipaddress.ip_address(token)
    except Exception as exc:
        raise ModuleValidationError(f"inputs.{key} must be a valid IPv4 address") from exc
    if not isinstance(ip, ipaddress.IPv4Address):
        raise ModuleValidationError(f"inputs.{key} must be an IPv4 address")
    return token


def _req_cidr30(inputs: dict[str, Any], key: str) -> ipaddress.IPv4Network:
    token = _req_str(inputs, key)
    try:
        net = ipaddress.ip_network(token, strict=False)
    except Exception as exc:
        raise ModuleValidationError(f"inputs.{key} must be a valid CIDR") from exc
    if not isinstance(net, ipaddress.IPv4Network):
        raise ModuleValidationError(f"inputs.{key} must be an IPv4 CIDR")
    if net.prefixlen != 30:
        raise ModuleValidationError(f"inputs.{key} must be a /30 CIDR")
    return net


def _asn(value: Any, key: str) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ModuleValidationError(f"inputs.{key} must be a number")
    n = int(value)
    if n < 1 or n > 4294967294:
        raise ModuleValidationError(f"inputs.{key} must be in range 1..4294967294")
    return n


def validate(inputs: dict[str, Any]) -> None:
    project_id = _req_str(inputs, "project_id")
    if not _PROJECT_ID_RE.fullmatch(project_id):
        raise ModuleValidationError("inputs.project_id is not a valid GCP project id format")

    _req_str(inputs, "region")
    _req_str(inputs, "network_self_link")
    _req_str(inputs, "router_name")

    _req_str(inputs, "ha_vpn_gateway_name")
    _req_str(inputs, "external_vpn_gateway_name")

    ip_a = _req_ipv4(inputs, "peer_ip_a")
    ip_b = _req_ipv4(inputs, "peer_ip_b")
    if ip_a == ip_b:
        raise ModuleValidationError("inputs.peer_ip_a and inputs.peer_ip_b must be different for TWO_IPS_REDUNDANCY")

    _asn(inputs.get("peer_asn"), "peer_asn")

    cidr_a = _req_cidr30(inputs, "tunnel_a_inside_cidr")
    cidr_b = _req_cidr30(inputs, "tunnel_b_inside_cidr")
    if cidr_a.overlaps(cidr_b):
        raise ModuleValidationError("inputs.tunnel_a_inside_cidr and inputs.tunnel_b_inside_cidr must not overlap")

    advertised = inputs.get("advertised_prefixes")
    if not isinstance(advertised, list) or not advertised:
        raise ModuleValidationError("inputs.advertised_prefixes must be a non-empty list")
    for idx, item in enumerate(advertised, start=1):
        if not isinstance(item, str) or not item.strip():
            raise ModuleValidationError(f"inputs.advertised_prefixes[{idx}] must be a non-empty string")
        try:
            ipaddress.ip_network(item.strip(), strict=False)
        except Exception as exc:
            raise ModuleValidationError(f"inputs.advertised_prefixes[{idx}] must be a valid CIDR") from exc

    priority = inputs.get("advertised_route_priority")
    if isinstance(priority, bool) or not isinstance(priority, (int, float)):
        raise ModuleValidationError("inputs.advertised_route_priority must be a number")
    if int(priority) < 0:
        raise ModuleValidationError("inputs.advertised_route_priority must be >= 0")

    _req_str(inputs, "shared_secret_a")
    _req_str(inputs, "shared_secret_b")
