"""
purpose: Validate inputs for module org/gcp/wan-cloud-nat.
Architecture Decision: ADR-0206 (module execution contract v1)
maintainer: HybridOps.Tech
"""

from __future__ import annotations

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


def _req_non_empty_list(inputs: dict[str, Any], key: str) -> list[str]:
    value = inputs.get(key)
    if not isinstance(value, list) or not value:
        raise ModuleValidationError(f"inputs.{key} must be a non-empty list")
    out: list[str] = []
    for idx, item in enumerate(value, start=1):
        token = str(item or "").strip()
        if not token:
            raise ModuleValidationError(f"inputs.{key}[{idx}] must be a non-empty string")
        out.append(token)
    return out


def _req_number(inputs: dict[str, Any], key: str, *, min_value: int = 1) -> int:
    raw = inputs.get(key)
    if isinstance(raw, bool) or not isinstance(raw, (int, float)):
        raise ModuleValidationError(f"inputs.{key} must be a number")
    value = int(raw)
    if value < min_value:
        raise ModuleValidationError(f"inputs.{key} must be >= {min_value}")
    return value


def validate(inputs: dict[str, Any]) -> None:
    project_id = _req_str(inputs, "project_id")
    if not _PROJECT_ID_RE.fullmatch(project_id):
        raise ModuleValidationError("inputs.project_id is not a valid GCP project id format")

    _req_str(inputs, "region")

    router_name = _req_str(inputs, "router_name")
    if not _NAME_RE.fullmatch(router_name):
        raise ModuleValidationError("inputs.router_name must be DNS-safe and match ^[a-z][a-z0-9-]{1,61}[a-z0-9]$")

    nat_name = _req_str(inputs, "nat_name")
    if not _NAME_RE.fullmatch(nat_name):
        raise ModuleValidationError("inputs.nat_name must be DNS-safe and match ^[a-z][a-z0-9-]{1,61}[a-z0-9]$")

    subnetwork_self_links = _req_non_empty_list(inputs, "subnetwork_self_links")
    if len(set(subnetwork_self_links)) != len(subnetwork_self_links):
        raise ModuleValidationError("inputs.subnetwork_self_links must not contain duplicates")

    source_ranges = _req_str(inputs, "subnetwork_source_ip_ranges_to_nat").upper()
    allowed_ranges = {"ALL_IP_RANGES", "LIST_OF_SECONDARY_IP_RANGES", "PRIMARY_IP_RANGE"}
    if source_ranges not in allowed_ranges:
        raise ModuleValidationError(
            "inputs.subnetwork_source_ip_ranges_to_nat must be one of ALL_IP_RANGES, PRIMARY_IP_RANGE, LIST_OF_SECONDARY_IP_RANGES"
        )

    auto_allocate = inputs.get("auto_allocate_external_ips")
    if not isinstance(auto_allocate, bool):
        raise ModuleValidationError("inputs.auto_allocate_external_ips must be a boolean")

    nat_ip_self_links = inputs.get("nat_ip_self_links")
    if nat_ip_self_links is None:
        nat_ip_self_links = []
    if not isinstance(nat_ip_self_links, list):
        raise ModuleValidationError("inputs.nat_ip_self_links must be a list when set")
    if auto_allocate and nat_ip_self_links:
        raise ModuleValidationError(
            "inputs.nat_ip_self_links must be empty when inputs.auto_allocate_external_ips=true"
        )
    if not auto_allocate and not nat_ip_self_links:
        raise ModuleValidationError(
            "inputs.nat_ip_self_links must be a non-empty list when inputs.auto_allocate_external_ips=false"
        )

    min_ports_per_vm = _req_number(inputs, "min_ports_per_vm", min_value=32)
    if min_ports_per_vm > 65536:
        raise ModuleValidationError("inputs.min_ports_per_vm must be <= 65536")

    endpoint_mapping = inputs.get("enable_endpoint_independent_mapping")
    if not isinstance(endpoint_mapping, bool):
        raise ModuleValidationError("inputs.enable_endpoint_independent_mapping must be a boolean")

    log_filter = _req_str(inputs, "log_filter").upper()
    if log_filter not in {"ERRORS_ONLY", "TRANSLATIONS_ONLY", "ALL"}:
        raise ModuleValidationError("inputs.log_filter must be ERRORS_ONLY, TRANSLATIONS_ONLY, or ALL")
