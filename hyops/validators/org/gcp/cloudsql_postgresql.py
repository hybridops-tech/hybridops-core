"""
purpose: Validate inputs for module org/gcp/cloudsql-postgresql.
Architecture Decision: ADR-0206 (module execution contract v1)
maintainer: HybridOps.Studio
"""

from __future__ import annotations

import re
from typing import Any

from hyops.validators.registry import ModuleValidationError


_PROJECT_ID_RE = re.compile(r"^[a-z][a-z0-9-]{4,28}[a-z0-9]$")
_INSTANCE_NAME_RE = re.compile(r"^[a-z](?:[a-z0-9-]{0,96}[a-z0-9])?$")
_RANGE_NAME_RE = re.compile(r"^[a-z][a-z0-9-]{0,62}$")


def _reject_placeholder(value: str, field: str) -> None:
    marker = value.strip().upper().replace("-", "_")
    if marker.startswith("CHANGE_ME") or "CHANGE_ME_" in marker:
        raise ModuleValidationError(f"{field} must not contain placeholder values (found {value!r})")


def validate(inputs: dict[str, Any]) -> None:
    def opt_str(key: str) -> str:
        v = inputs.get(key)
        if v is None:
            return ""
        if not isinstance(v, str):
            raise ModuleValidationError(f"inputs.{key} must be a string when set")
        return v.strip()

    def req_str(key: str) -> str:
        value = opt_str(key)
        if not value:
            raise ModuleValidationError(f"inputs.{key} must be a non-empty string")
        return value

    def opt_bool(key: str) -> bool | None:
        v = inputs.get(key)
        if v is None:
            return None
        if not isinstance(v, bool):
            raise ModuleValidationError(f"inputs.{key} must be a boolean when set")
        return v

    def opt_int(key: str) -> int:
        v = inputs.get(key)
        if v is None:
            return 0
        if isinstance(v, bool) or not isinstance(v, int):
            raise ModuleValidationError(f"inputs.{key} must be an integer when set")
        return v

    def opt_dict(key: str) -> dict[str, Any]:
        v = inputs.get(key)
        if v is None:
            return {}
        if not isinstance(v, dict):
            raise ModuleValidationError(f"inputs.{key} must be a mapping when set")
        return v

    project_id = opt_str("project_id")
    if project_id:
        _reject_placeholder(project_id, "inputs.project_id")
        if not _PROJECT_ID_RE.fullmatch(project_id):
            raise ModuleValidationError("inputs.project_id is not a valid GCP project id format")

    network_project_id = opt_str("network_project_id")
    if network_project_id:
        _reject_placeholder(network_project_id, "inputs.network_project_id")
        if not _PROJECT_ID_RE.fullmatch(network_project_id):
            raise ModuleValidationError("inputs.network_project_id is not a valid GCP project id format")

    private_network = opt_str("private_network")
    if private_network:
        _reject_placeholder(private_network, "inputs.private_network")

    req_str("region")

    instance_name = req_str("instance_name")
    _reject_placeholder(instance_name, "inputs.instance_name")
    if not _INSTANCE_NAME_RE.fullmatch(instance_name):
        raise ModuleValidationError(
            "inputs.instance_name must match ^[a-z](?:[a-z0-9-]{0,96}[a-z0-9])?$"
        )

    database_version = req_str("database_version").upper()
    if not database_version.startswith("POSTGRES_"):
        raise ModuleValidationError("inputs.database_version must be a supported PostgreSQL version token, e.g. POSTGRES_16")

    edition = req_str("edition").upper()
    if edition not in ("ENTERPRISE", "ENTERPRISE_PLUS"):
        raise ModuleValidationError("inputs.edition must be one of: ENTERPRISE, ENTERPRISE_PLUS")

    availability_type = req_str("availability_type").upper()
    if availability_type not in ("ZONAL", "REGIONAL"):
        raise ModuleValidationError("inputs.availability_type must be one of: ZONAL, REGIONAL")

    _ = req_str("tier")

    disk_size_gb = opt_int("disk_size_gb")
    if disk_size_gb <= 0:
        raise ModuleValidationError("inputs.disk_size_gb must be > 0")

    disk_type = req_str("disk_type").upper()
    if disk_type not in ("PD_SSD", "PD_HDD"):
        raise ModuleValidationError("inputs.disk_type must be one of: PD_SSD, PD_HDD")

    backup_enabled = opt_bool("backup_enabled")
    pitr_enabled = opt_bool("point_in_time_recovery_enabled")
    if pitr_enabled is True and backup_enabled is False:
        raise ModuleValidationError(
            "inputs.point_in_time_recovery_enabled=true requires inputs.backup_enabled=true"
        )

    ipv4_enabled = opt_bool("ipv4_enabled")
    create_private_service_connection = opt_bool("create_private_service_connection")
    _ = opt_bool("manage_shared_vpc_attachment")
    _ = opt_bool("deletion_protection")

    range_name = opt_str("allocated_ip_range_name")
    if range_name:
        _reject_placeholder(range_name, "inputs.allocated_ip_range_name")
        if not _RANGE_NAME_RE.fullmatch(range_name):
            raise ModuleValidationError(
                "inputs.allocated_ip_range_name must match ^[a-z][a-z0-9-]{0,62}$"
            )

    network_state_ref = opt_str("network_state_ref")
    if not private_network and not network_state_ref:
        raise ModuleValidationError(
            "one of inputs.private_network or inputs.network_state_ref is required"
        )

    if not project_id and not opt_str("project_state_ref") and not network_state_ref:
        raise ModuleValidationError(
            "one of inputs.project_id or inputs.project_state_ref is required"
        )

    if ipv4_enabled is False and not (private_network or network_state_ref):
        raise ModuleValidationError(
            "inputs.ipv4_enabled=false requires private networking via inputs.private_network or inputs.network_state_ref"
        )

    if create_private_service_connection is False and not range_name:
        raise ModuleValidationError(
            "inputs.allocated_ip_range_name is required when inputs.create_private_service_connection=false"
        )

    if create_private_service_connection is True and private_network and not (network_project_id or network_state_ref):
        raise ModuleValidationError(
            "inputs.network_project_id is required when inputs.create_private_service_connection=true "
            "and using explicit inputs.private_network without inputs.network_state_ref"
        )

    labels = opt_dict("labels")
    for raw_key, raw_value in labels.items():
        if not isinstance(raw_key, str) or not raw_key.strip():
            raise ModuleValidationError("inputs.labels keys must be non-empty strings")
        if not isinstance(raw_value, str):
            raise ModuleValidationError(f"inputs.labels[{raw_key!r}] must be a string")

    flags = opt_dict("database_flags")
    for raw_key, raw_value in flags.items():
        if not isinstance(raw_key, str) or not raw_key.strip():
            raise ModuleValidationError("inputs.database_flags keys must be non-empty strings")
        if not isinstance(raw_value, str):
            raise ModuleValidationError(f"inputs.database_flags[{raw_key!r}] must be a string")
