"""
purpose: Validate inputs for platform/gcp/gke-cluster module.
Architecture Decision: ADR-N/A (gke-cluster validator)
maintainer: HybridOps
"""

from __future__ import annotations

import ipaddress
import re
from typing import Any

from hyops.validators.common import (
    check_no_placeholder,
    opt_bool,
    opt_int,
    opt_str,
    require_non_empty_str,
)
from hyops.validators.registry import ModuleValidationError


_PROJECT_ID_RE = re.compile(r"^[a-z][a-z0-9-]{4,28}[a-z0-9]$")
_NAME_RE = re.compile(r"^[a-z][a-z0-9-]{1,61}[a-z0-9]$")
_LOCATION_RE = re.compile(r"^[a-z]+-[a-z0-9]+[0-9](?:-[a-z])?$")
_SA_EMAIL_RE = re.compile(r"^[a-z][a-z0-9-]{4,28}[a-z0-9]@[a-z][a-z0-9-]{4,28}[a-z0-9]\.iam\.gserviceaccount\.com$")


def _req_str(inputs: dict[str, Any], key: str) -> str:
    return check_no_placeholder(
        require_non_empty_str(inputs.get(key), f"inputs.{key}"),
        f"inputs.{key}",
    )


def _opt_str(inputs: dict[str, Any], key: str) -> str:
    v = opt_str(inputs.get(key), f"inputs.{key}")
    return check_no_placeholder(v, f"inputs.{key}") if v else v


def _opt_bool(inputs: dict[str, Any], key: str) -> bool | None:
    return opt_bool(inputs.get(key), f"inputs.{key}")


def _opt_int(inputs: dict[str, Any], key: str) -> int | None:
    return opt_int(inputs.get(key), f"inputs.{key}", minimum=1)


def _req_list_of_strings(inputs: dict[str, Any], key: str) -> list[str]:
    value = inputs.get(key)
    if not isinstance(value, list) or not value:
        raise ModuleValidationError(f"inputs.{key} must be a non-empty list")
    out: list[str] = []
    for idx, item in enumerate(value, start=1):
        if not isinstance(item, str) or not item.strip():
            raise ModuleValidationError(f"inputs.{key}[{idx}] must be a non-empty string")
        out.append(item.strip())
    return out


def validate(inputs: dict[str, Any]) -> None:
    project_id = _req_str(inputs, "project_id")
    if not _PROJECT_ID_RE.fullmatch(project_id):
        raise ModuleValidationError("inputs.project_id is not a valid GCP project id format")

    region = _req_str(inputs, "region")
    location = _req_str(inputs, "location")
    if not _LOCATION_RE.fullmatch(location):
        raise ModuleValidationError("inputs.location must be a valid GCP region or zone token")
    if not location.startswith(f"{region}-") and location != region:
        raise ModuleValidationError("inputs.location must belong to inputs.region")

    cluster_name = _req_str(inputs, "cluster_name")
    if not _NAME_RE.fullmatch(cluster_name):
        raise ModuleValidationError("inputs.cluster_name must be DNS-safe and match ^[a-z][a-z0-9-]{1,61}[a-z0-9]$")

    network = _req_str(inputs, "network")
    subnetwork = _req_str(inputs, "subnetwork")
    pods_secondary_range_name = _req_str(inputs, "pods_secondary_range_name")
    services_secondary_range_name = _req_str(inputs, "services_secondary_range_name")
    if pods_secondary_range_name == services_secondary_range_name:
        raise ModuleValidationError(
            "inputs.pods_secondary_range_name and inputs.services_secondary_range_name must be different"
        )

    _req_str(inputs, "release_channel")
    _req_str(inputs, "node_pool_name")
    _req_str(inputs, "machine_type")
    _opt_int(inputs, "node_count")
    _opt_int(inputs, "disk_size_gb")
    node_service_account = inputs.get("node_service_account")
    if node_service_account is not None:
        if not isinstance(node_service_account, str):
            raise ModuleValidationError("inputs.node_service_account must be a string")
        if node_service_account.strip():
            token = _req_str(inputs, "node_service_account")
            if not _SA_EMAIL_RE.fullmatch(token):
                raise ModuleValidationError(
                    "inputs.node_service_account must be a valid GCP service account email"
                )

    node_service_account_id = inputs.get("node_service_account_id")
    if node_service_account_id is not None:
        if not isinstance(node_service_account_id, str):
            raise ModuleValidationError("inputs.node_service_account_id must be a string")
        if node_service_account_id.strip():
            token = _req_str(inputs, "node_service_account_id")
            if not _NAME_RE.fullmatch(token):
                raise ModuleValidationError(
                    "inputs.node_service_account_id must be DNS-safe and match ^[a-z][a-z0-9-]{1,61}[a-z0-9]$"
                )

    enable_private_nodes = _opt_bool(inputs, "enable_private_nodes")
    enable_private_endpoint = _opt_bool(inputs, "enable_private_endpoint")
    deletion_protection = _opt_bool(inputs, "deletion_protection")
    if deletion_protection and cluster_name.endswith("-drill"):
        raise ModuleValidationError("inputs.deletion_protection should be false for disposable drill clusters")

    master_ipv4_cidr_block = _req_str(inputs, "master_ipv4_cidr_block")
    try:
        master_net = ipaddress.ip_network(master_ipv4_cidr_block, strict=False)
    except Exception as exc:
        raise ModuleValidationError("inputs.master_ipv4_cidr_block must be a valid CIDR") from exc
    if not isinstance(master_net, ipaddress.IPv4Network):
        raise ModuleValidationError("inputs.master_ipv4_cidr_block must be an IPv4 CIDR")

    authorized = inputs.get("master_authorized_networks")
    if not isinstance(authorized, list):
        raise ModuleValidationError("inputs.master_authorized_networks must be a list")
    if not enable_private_endpoint and not authorized:
        raise ModuleValidationError(
            "inputs.master_authorized_networks must contain at least one CIDR when inputs.enable_private_endpoint=false"
        )
    for idx, item in enumerate(authorized, start=1):
        if not isinstance(item, dict):
            raise ModuleValidationError(f"inputs.master_authorized_networks[{idx}] must be a mapping")
        cidr = item.get("cidr")
        if not isinstance(cidr, str) or not cidr.strip():
            raise ModuleValidationError(f"inputs.master_authorized_networks[{idx}].cidr must be a non-empty string")
        try:
            ipaddress.ip_network(cidr.strip(), strict=False)
        except Exception as exc:
            raise ModuleValidationError(
                f"inputs.master_authorized_networks[{idx}].cidr must be a valid CIDR"
            ) from exc
        display_name = item.get("display_name")
        if display_name is not None and (not isinstance(display_name, str) or not display_name.strip()):
            raise ModuleValidationError(
                f"inputs.master_authorized_networks[{idx}].display_name must be a non-empty string when set"
            )

    tags = _req_list_of_strings(inputs, "tags")
    if not tags:
        raise ModuleValidationError("inputs.tags must contain at least one tag")

    labels = inputs.get("labels")
    if labels is not None:
        if not isinstance(labels, dict):
            raise ModuleValidationError("inputs.labels must be a mapping when set")
        for key, value in labels.items():
            if not isinstance(key, str) or not key.strip():
                raise ModuleValidationError("inputs.labels keys must be non-empty strings")
            if not isinstance(value, str):
                raise ModuleValidationError(f"inputs.labels[{key!r}] must be a string")

    node_locations = inputs.get("node_locations")
    if node_locations not in (None, []):
        for idx, item in enumerate(_req_list_of_strings(inputs, "node_locations"), start=1):
            if not item.startswith(f"{region}-"):
                raise ModuleValidationError(f"inputs.node_locations[{idx}] must belong to inputs.region")

    if enable_private_endpoint and not enable_private_nodes:
        raise ModuleValidationError(
            "inputs.enable_private_endpoint=true requires inputs.enable_private_nodes=true"
        )

    # explicit use to keep required strings validated even if only resolved from state.
    _ = network
    _ = subnetwork
    _ = pods_secondary_range_name
    _ = services_secondary_range_name
