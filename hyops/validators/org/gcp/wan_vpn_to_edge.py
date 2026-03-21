"""
purpose: Validate inputs for module org/gcp/wan-vpn-to-edge.
Architecture Decision: ADR-0206 (module execution contract v1)
maintainer: HybridOps.Tech
"""

from __future__ import annotations

import ipaddress
import re
from typing import Any

from hyops.validators.common import (
    normalize_required_env,
    opt_str,
    require_non_empty_str,
)
from hyops.validators.registry import ModuleValidationError


_PROJECT_ID_RE = re.compile(r"^[a-z][a-z0-9-]{4,28}[a-z0-9]$")


def _req_str(inputs: dict[str, Any], key: str) -> str:
    return require_non_empty_str(inputs.get(key), f"inputs.{key}")


def _opt_str(inputs: dict[str, Any], key: str) -> str:
    return opt_str(inputs.get(key), f"inputs.{key}")


def _reject_placeholder(value: str, field: str) -> None:
    marker = value.strip().upper()
    if marker.startswith("CHANGE_ME") or "CHANGE_ME_" in marker:
        raise ModuleValidationError(f"{field} must not contain placeholder values (found {value!r})")


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

    for key in ("cloud_core_cidr", "cloud_workloads_cidr", "cloud_workloads_pods_cidr"):
        raw = opt_str(inputs.get(key), f"inputs.{key}")
        if not raw:
            continue
        try:
            ipaddress.ip_network(raw, strict=False)
        except Exception as exc:
            raise ModuleValidationError(f"inputs.{key} must be a valid CIDR when set") from exc

    for key in (
        "auto_include_cloud_core_cidr",
        "auto_include_cloud_workloads_cidr",
        "auto_include_cloud_workloads_pods_cidr",
    ):
        if key in inputs and not isinstance(inputs.get(key), bool):
            raise ModuleValidationError(f"inputs.{key} must be a boolean when set")

    advertised = inputs.get("advertised_prefixes")
    if not isinstance(advertised, list):
        raise ModuleValidationError("inputs.advertised_prefixes must be a list")
    for idx, item in enumerate(advertised, start=1):
        if not isinstance(item, str) or not item.strip():
            raise ModuleValidationError(f"inputs.advertised_prefixes[{idx}] must be a non-empty string")
        try:
            ipaddress.ip_network(item.strip(), strict=False)
        except Exception as exc:
            raise ModuleValidationError(f"inputs.advertised_prefixes[{idx}] must be a valid CIDR") from exc
    if not advertised and not any(
        bool(inputs.get(key))
        for key in (
            "auto_include_cloud_core_cidr",
            "auto_include_cloud_workloads_cidr",
            "auto_include_cloud_workloads_pods_cidr",
        )
    ):
        raise ModuleValidationError(
            "inputs.advertised_prefixes must be non-empty unless state driven cloud prefix inclusion is enabled"
        )

    priority = inputs.get("advertised_route_priority")
    if isinstance(priority, bool) or not isinstance(priority, (int, float)):
        raise ModuleValidationError("inputs.advertised_route_priority must be a number")
    if int(priority) < 0:
        raise ModuleValidationError("inputs.advertised_route_priority must be >= 0")

    required_env = normalize_required_env(inputs.get("required_env"), "inputs.required_env")

    for suffix in ("a", "b"):
        secret_field = f"shared_secret_{suffix}"
        env_field = f"shared_secret_{suffix}_env"
        secret_value = _opt_str(inputs, secret_field)
        env_value = _opt_str(inputs, env_field)

        if secret_value:
            _reject_placeholder(secret_value, f"inputs.{secret_field}")
        if env_value:
            _reject_placeholder(env_value, f"inputs.{env_field}")

        if not secret_value and not env_value:
            raise ModuleValidationError(
                f"one of inputs.{secret_field} or inputs.{env_field} is required"
            )
        if not secret_value and env_value and env_value not in required_env:
            raise ModuleValidationError(
                f"inputs.required_env must include: {env_value} "
                f"(referenced by inputs.{env_field})"
            )
