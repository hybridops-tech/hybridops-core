"""
purpose: Validate inputs for module org/gcp/wan-hub-network.
Architecture Decision: ADR-0206 (module execution contract v1)
maintainer: HybridOps.Studio
"""

from __future__ import annotations

import ipaddress
import re
from typing import Any

from hyops.validators.registry import ModuleValidationError


_PROJECT_ID_RE = re.compile(r"^[a-z][a-z0-9-]{4,28}[a-z0-9]$")
_NAME_RE = re.compile(r"^[a-z][a-z0-9-]{1,61}[a-z0-9]$")


def _req_str(inputs: dict[str, Any], key: str) -> str:
    v = inputs.get(key)
    if not isinstance(v, str) or not v.strip():
        raise ModuleValidationError(f"inputs.{key} must be a non-empty string")
    return v.strip()


def _req_cidr(inputs: dict[str, Any], key: str) -> ipaddress.IPv4Network:
    token = _req_str(inputs, key)
    try:
        net = ipaddress.ip_network(token, strict=False)
    except Exception as exc:
        raise ModuleValidationError(f"inputs.{key} must be a valid CIDR") from exc
    if not isinstance(net, ipaddress.IPv4Network):
        raise ModuleValidationError(f"inputs.{key} must be an IPv4 CIDR")
    return net


def _req_cidr_list(inputs: dict[str, Any], key: str) -> None:
    v = inputs.get(key)
    if not isinstance(v, list) or not v:
        raise ModuleValidationError(f"inputs.{key} must be a non-empty list")
    for idx, item in enumerate(v, start=1):
        if not isinstance(item, str) or not item.strip():
            raise ModuleValidationError(f"inputs.{key}[{idx}] must be a non-empty string")
        try:
            ipaddress.ip_network(item.strip(), strict=False)
        except Exception as exc:
            raise ModuleValidationError(f"inputs.{key}[{idx}] must be a valid CIDR") from exc


def validate(inputs: dict[str, Any]) -> None:
    project_id = _req_str(inputs, "project_id")
    if not _PROJECT_ID_RE.fullmatch(project_id):
        raise ModuleValidationError("inputs.project_id is not a valid GCP project id format")

    _req_str(inputs, "region")

    network_name = _req_str(inputs, "network_name")
    if not _NAME_RE.fullmatch(network_name):
        raise ModuleValidationError("inputs.network_name must be DNS-safe and match ^[a-z][a-z0-9-]{1,61}[a-z0-9]$")

    routing_mode = _req_str(inputs, "routing_mode").upper()
    if routing_mode not in ("GLOBAL", "REGIONAL"):
        raise ModuleValidationError("inputs.routing_mode must be GLOBAL or REGIONAL")

    subnet_core_name = _req_str(inputs, "subnet_core_name")
    subnet_workloads_name = _req_str(inputs, "subnet_workloads_name")
    if subnet_core_name == subnet_workloads_name:
        raise ModuleValidationError("inputs.subnet_core_name and inputs.subnet_workloads_name must be different")

    core = _req_cidr(inputs, "subnet_core_cidr")
    workloads = _req_cidr(inputs, "subnet_workloads_cidr")
    if core.overlaps(workloads):
        raise ModuleValidationError("inputs.subnet_core_cidr and inputs.subnet_workloads_cidr must not overlap")

    enable_iap_ssh = inputs.get("enable_iap_ssh")
    if enable_iap_ssh is not None and not isinstance(enable_iap_ssh, bool):
        raise ModuleValidationError("inputs.enable_iap_ssh must be a boolean when set")

    _req_cidr_list(inputs, "internal_allow_cidrs")

    labels = inputs.get("labels")
    if labels is not None:
        if not isinstance(labels, dict):
            raise ModuleValidationError("inputs.labels must be a mapping when set")
        for k, v in labels.items():
            if not isinstance(k, str) or not k.strip():
                raise ModuleValidationError("inputs.labels keys must be non-empty strings")
            if not isinstance(v, str):
                raise ModuleValidationError(f"inputs.labels[{k!r}] must be a string")
