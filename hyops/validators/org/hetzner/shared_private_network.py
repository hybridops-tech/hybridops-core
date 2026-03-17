"""hyops.validators.org.hetzner.shared_private_network

purpose: Validate inputs for org/hetzner/shared-private-network.
maintainer: HybridOps.Tech
"""

from __future__ import annotations

import ipaddress
from typing import Any

from hyops.validators.registry import ModuleValidationError


def _req_str(inputs: dict[str, Any], key: str) -> str:
    value = inputs.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ModuleValidationError(f"inputs.{key} must be a non-empty string")
    token = value.strip()
    marker = token.upper().replace("-", "_")
    if marker.startswith("CHANGE_ME") or "CHANGE_ME_" in marker:
        raise ModuleValidationError(f"inputs.{key} must not contain placeholder values (found {token!r})")
    return token


def _opt_map(inputs: dict[str, Any], key: str) -> dict[str, Any]:
    value = inputs.get(key)
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ModuleValidationError(f"inputs.{key} must be a mapping when set")
    return value


def validate(inputs: dict[str, Any]) -> None:
    _req_str(inputs, "network_zone")
    _req_str(inputs, "private_network_name")
    private_network_cidr = _req_str(inputs, "private_network_cidr")

    try:
        network = ipaddress.ip_network(private_network_cidr, strict=False)
    except Exception as exc:
        raise ModuleValidationError("inputs.private_network_cidr must be a valid CIDR") from exc
    if not isinstance(network, ipaddress.IPv4Network):
        raise ModuleValidationError("inputs.private_network_cidr must be an IPv4 CIDR")

    labels = _opt_map(inputs, "labels")
    for key, value in labels.items():
        if not isinstance(key, str) or not key.strip():
            raise ModuleValidationError("inputs.labels keys must be non-empty strings")
        if not isinstance(value, str):
            raise ModuleValidationError(f"inputs.labels[{key!r}] must be a string")
