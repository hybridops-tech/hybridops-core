"""
purpose: Validate inputs for module org/gcp/wan-hub-network.
Architecture Decision: ADR-0206 (module execution contract v1)
maintainer: HybridOps.Tech
"""

from __future__ import annotations

import ipaddress
import re
from typing import Any

from hyops.validators.common import (
    opt_str,
    require_non_empty_str,
)
from hyops.validators.registry import ModuleValidationError


_PROJECT_ID_RE = re.compile(r"^[a-z][a-z0-9-]{4,28}[a-z0-9]$")
_NAME_RE = re.compile(r"^[a-z][a-z0-9-]{1,61}[a-z0-9]$")


def _req_str(inputs: dict[str, Any], key: str) -> str:
    return require_non_empty_str(inputs.get(key), f"inputs.{key}")


def _opt_str(inputs: dict[str, Any], key: str) -> str:
    return opt_str(inputs.get(key), f"inputs.{key}")


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
    project_state_ref = str(inputs.get("project_state_ref") or "").strip()
    project_id = str(inputs.get("project_id") or "").strip()
    if project_state_ref:
        if "/" not in project_state_ref:
            raise ModuleValidationError("inputs.project_state_ref must look like a module state ref when set")
    else:
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

    enable_secondary_ranges = inputs.get("enable_workloads_gke_secondary_ranges")
    if enable_secondary_ranges is not None and not isinstance(enable_secondary_ranges, bool):
        raise ModuleValidationError("inputs.enable_workloads_gke_secondary_ranges must be a boolean when set")

    if bool(enable_secondary_ranges):
        pods_range_name = _req_str(inputs, "subnet_workloads_pods_secondary_range_name")
        services_range_name = _req_str(inputs, "subnet_workloads_services_secondary_range_name")
        if pods_range_name == services_range_name:
            raise ModuleValidationError(
                "inputs.subnet_workloads_pods_secondary_range_name and "
                "inputs.subnet_workloads_services_secondary_range_name must be different"
            )

        pods = _req_cidr(inputs, "subnet_workloads_pods_secondary_range_cidr")
        services = _req_cidr(inputs, "subnet_workloads_services_secondary_range_cidr")
        if pods.overlaps(core) or pods.overlaps(workloads):
            raise ModuleValidationError(
                "inputs.subnet_workloads_pods_secondary_range_cidr must not overlap core/workloads subnets"
            )
        if services.overlaps(core) or services.overlaps(workloads):
            raise ModuleValidationError(
                "inputs.subnet_workloads_services_secondary_range_cidr must not overlap core/workloads subnets"
            )
        if pods.overlaps(services):
            raise ModuleValidationError(
                "inputs.subnet_workloads_pods_secondary_range_cidr and "
                "inputs.subnet_workloads_services_secondary_range_cidr must not overlap"
            )

    enable_iap_ssh = inputs.get("enable_iap_ssh")
    if enable_iap_ssh is not None and not isinstance(enable_iap_ssh, bool):
        raise ModuleValidationError("inputs.enable_iap_ssh must be a boolean when set")

    _req_cidr_list(inputs, "internal_allow_cidrs")
