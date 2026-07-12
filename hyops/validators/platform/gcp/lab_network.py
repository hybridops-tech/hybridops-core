"""
purpose: Validate inputs for platform/gcp/lab-network.
Architecture Decision: ADR-0206 (module execution contract v1)
maintainer: HybridOps.Tech
"""

from __future__ import annotations

import ipaddress
import re
from typing import Any

from hyops.validators.common import require_non_empty_str
from hyops.validators.registry import ModuleValidationError


_PROJECT_ID_RE = re.compile(r"^[a-z][a-z0-9-]{4,28}[a-z0-9]$")
_NAME_RE = re.compile(r"^[a-z][a-z0-9-]{1,61}[a-z0-9]$")
_REGION_RE = re.compile(r"^[a-z]+-[a-z0-9]+[0-9]$")
_RFC1918_NETWORKS = (
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
)


def _req_str(inputs: dict[str, Any], key: str) -> str:
    return require_non_empty_str(inputs.get(key), f"inputs.{key}")


def _reject_placeholder(value: str, key: str) -> None:
    if "CHANGE_ME" in value.strip().upper():
        raise ModuleValidationError(f"inputs.{key} must not contain placeholder values")


def _req_name(inputs: dict[str, Any], key: str) -> str:
    value = _req_str(inputs, key)
    _reject_placeholder(value, key)
    if not _NAME_RE.fullmatch(value):
        raise ModuleValidationError(
            f"inputs.{key} must be DNS-safe and match ^[a-z][a-z0-9-]{{1,61}}[a-z0-9]$"
        )
    return value


def _req_bool(inputs: dict[str, Any], key: str) -> bool:
    value = inputs.get(key)
    if not isinstance(value, bool):
        raise ModuleValidationError(f"inputs.{key} must be a boolean")
    return value


def _req_ipv4_network(inputs: dict[str, Any], key: str) -> ipaddress.IPv4Network:
    value = _req_str(inputs, key)
    _reject_placeholder(value, key)
    try:
        network = ipaddress.ip_network(value, strict=True)
    except ValueError as exc:
        raise ModuleValidationError(f"inputs.{key} must be a canonical IPv4 CIDR") from exc
    if not isinstance(network, ipaddress.IPv4Network):
        raise ModuleValidationError(f"inputs.{key} must be an IPv4 CIDR")
    return network


def _req_cidr_list(inputs: dict[str, Any], key: str) -> list[ipaddress.IPv4Network]:
    value = inputs.get(key)
    if not isinstance(value, list) or not value:
        raise ModuleValidationError(f"inputs.{key} must be a non-empty list")

    networks: list[ipaddress.IPv4Network] = []
    for idx, item in enumerate(value, start=1):
        token = str(item or "").strip()
        try:
            network = ipaddress.ip_network(token, strict=True)
        except ValueError as exc:
            raise ModuleValidationError(f"inputs.{key}[{idx}] must be a canonical IPv4 CIDR") from exc
        if not isinstance(network, ipaddress.IPv4Network):
            raise ModuleValidationError(f"inputs.{key}[{idx}] must be an IPv4 CIDR")
        networks.append(network)

    if len(set(networks)) != len(networks):
        raise ModuleValidationError(f"inputs.{key} must not contain duplicate CIDRs")
    return networks


def _req_tag_list(inputs: dict[str, Any], key: str) -> list[str]:
    value = inputs.get(key)
    if not isinstance(value, list) or not value:
        raise ModuleValidationError(f"inputs.{key} must be a non-empty list")
    tags: list[str] = []
    for idx, item in enumerate(value, start=1):
        token = str(item or "").strip()
        if not token or not _NAME_RE.fullmatch(token):
            raise ModuleValidationError(f"inputs.{key}[{idx}] must be a DNS-safe network tag")
        tags.append(token)
    if len(set(tags)) != len(tags):
        raise ModuleValidationError(f"inputs.{key} must not contain duplicate tags")
    return tags


def validate(inputs: dict[str, Any]) -> None:
    project_id = str(inputs.get("project_id") or "").strip()
    if project_id:
        _reject_placeholder(project_id, "project_id")
        if not _PROJECT_ID_RE.fullmatch(project_id):
            raise ModuleValidationError("inputs.project_id is not a valid GCP project id format")

    region = _req_str(inputs, "region")
    _reject_placeholder(region, "region")
    if not _REGION_RE.fullmatch(region):
        raise ModuleValidationError("inputs.region is not a valid GCP region format")

    _req_name(inputs, "network_name")
    _req_name(inputs, "subnetwork_name")
    _req_name(inputs, "router_name")
    _req_name(inputs, "nat_name")

    routing_mode = _req_str(inputs, "routing_mode").upper()
    if routing_mode not in {"REGIONAL", "GLOBAL"}:
        raise ModuleValidationError("inputs.routing_mode must be REGIONAL or GLOBAL")

    subnetwork = _req_ipv4_network(inputs, "subnetwork_cidr")
    if not any(subnetwork.subnet_of(parent) for parent in _RFC1918_NETWORKS):
        raise ModuleValidationError("inputs.subnetwork_cidr must be within an RFC1918 private range")

    _req_bool(inputs, "enable_private_google_access")
    enable_iap = _req_bool(inputs, "enable_iap_ssh")
    if enable_iap:
        _req_cidr_list(inputs, "iap_source_cidrs")
        _req_tag_list(inputs, "iap_target_tags")

    raw_ports = inputs.get("nat_min_ports_per_vm")
    if isinstance(raw_ports, bool) or not isinstance(raw_ports, int):
        raise ModuleValidationError("inputs.nat_min_ports_per_vm must be an integer")
    if raw_ports < 32 or raw_ports > 65536:
        raise ModuleValidationError("inputs.nat_min_ports_per_vm must be between 32 and 65536")

    _req_bool(inputs, "nat_enable_endpoint_independent_mapping")
    log_filter = _req_str(inputs, "nat_log_filter").upper()
    if log_filter not in {"ERRORS_ONLY", "TRANSLATIONS_ONLY", "ALL"}:
        raise ModuleValidationError(
            "inputs.nat_log_filter must be ERRORS_ONLY, TRANSLATIONS_ONLY, or ALL"
        )
