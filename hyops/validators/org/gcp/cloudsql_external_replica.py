"""
purpose: Validate inputs for module org/gcp/cloudsql-external-replica.
Architecture Decision: ADR-0206 (module execution contract v1)
maintainer: HybridOps.Tech
"""

from __future__ import annotations

import ipaddress
import re
from typing import Any

from hyops.validators.registry import ModuleValidationError


_PROJECT_ID_RE = re.compile(r"^[a-z][a-z0-9-]{4,28}[a-z0-9]$")
_INSTANCE_NAME_RE = re.compile(r"^[a-z](?:[a-z0-9-]{0,96}[a-z0-9])?$")


def _opt_str(inputs: dict[str, Any], key: str) -> str:
    value = inputs.get(key)
    if value is None:
        return ""
    if not isinstance(value, str):
        raise ModuleValidationError(f"inputs.{key} must be a string when set")
    return value.strip()


def _req_str(inputs: dict[str, Any], key: str) -> str:
    value = _opt_str(inputs, key)
    if not value:
        raise ModuleValidationError(f"inputs.{key} must be a non-empty string")
    return value


def _opt_bool(inputs: dict[str, Any], key: str) -> bool | None:
    value = inputs.get(key)
    if value is None:
        return None
    if not isinstance(value, bool):
        raise ModuleValidationError(f"inputs.{key} must be a boolean when set")
    return value


def _reject_placeholder(value: str, field: str) -> None:
    marker = value.strip().upper().replace("-", "_")
    if marker.startswith("CHANGE_ME") or "CHANGE_ME_" in marker:
        raise ModuleValidationError(f"{field} must not contain placeholder values (found {value!r})")


def _validate_ipv4(value: str, field: str) -> None:
    try:
        ip = ipaddress.ip_address(value)
    except Exception as exc:
        raise ModuleValidationError(f"{field} must be a valid IP address") from exc
    if not isinstance(ip, ipaddress.IPv4Address):
        raise ModuleValidationError(f"{field} must be an IPv4 address")


def validate(inputs: dict[str, Any]) -> None:
    apply_mode = _req_str(inputs, "apply_mode").lower()
    if apply_mode not in ("assess", "establish", "status"):
        raise ModuleValidationError("inputs.apply_mode must be one of: assess, establish, status")

    replication_mode = _req_str(inputs, "replication_mode").lower()
    if replication_mode != "logical":
        raise ModuleValidationError("inputs.replication_mode must be logical (v1)")

    source_contract_version = inputs.get("source_contract_version")
    if isinstance(source_contract_version, bool) or not isinstance(source_contract_version, int):
        raise ModuleValidationError("inputs.source_contract_version must be an integer")
    if source_contract_version != 1:
        raise ModuleValidationError("inputs.source_contract_version must be 1")

    _ = _opt_str(inputs, "replica_state_ref")
    _ = _opt_str(inputs, "replica_state_env")
    required_job_states = inputs.get("required_migration_job_states")
    if required_job_states is None:
        required_job_states = []
    if not isinstance(required_job_states, list):
        raise ModuleValidationError("inputs.required_migration_job_states must be a list when set")
    for idx, item in enumerate(required_job_states, start=1):
        if not isinstance(item, str) or not item.strip():
            raise ModuleValidationError(
                f"inputs.required_migration_job_states[{idx}] must be a non-empty string"
            )

    source_state_ref = _opt_str(inputs, "source_state_ref")
    source_host = _opt_str(inputs, "source_host")
    if not source_state_ref and not source_host:
        raise ModuleValidationError(
            "one of inputs.source_state_ref or inputs.source_host is required"
        )
    if source_host:
        _validate_ipv4(source_host, "inputs.source_host")

    source_contract = inputs.get("source_contract")
    if source_contract is not None and not isinstance(source_contract, dict):
        raise ModuleValidationError("inputs.source_contract must be a mapping when set")

    target_state_ref = _opt_str(inputs, "managed_target_state_ref")
    target_project_id = _opt_str(inputs, "target_project_id")
    target_region = _opt_str(inputs, "target_region")
    target_instance_name = _opt_str(inputs, "target_instance_name")

    if apply_mode == "assess":
        if not target_state_ref and not (target_project_id and target_region and target_instance_name):
            raise ModuleValidationError(
                "for apply_mode=assess, provide inputs.managed_target_state_ref or the explicit "
                "target tuple (target_project_id, target_region, target_instance_name)"
            )

        if target_project_id:
            _reject_placeholder(target_project_id, "inputs.target_project_id")
            if not _PROJECT_ID_RE.fullmatch(target_project_id):
                raise ModuleValidationError("inputs.target_project_id is not a valid GCP project id format")

        if target_instance_name:
            _reject_placeholder(target_instance_name, "inputs.target_instance_name")
            if not _INSTANCE_NAME_RE.fullmatch(target_instance_name):
                raise ModuleValidationError(
                    "inputs.target_instance_name must match ^[a-z](?:[a-z0-9-]{0,96}[a-z0-9])?$"
                )

        target_db_host = _opt_str(inputs, "target_db_host")
        if target_db_host:
            _validate_ipv4(target_db_host, "inputs.target_db_host")

    _ = _opt_str(inputs, "target_connection_name")
    _ = _opt_str(inputs, "source_db_name")
    _ = _opt_str(inputs, "source_db_user")
    _ = _opt_str(inputs, "source_leader_name")
    _ = _opt_str(inputs, "source_leader_host")
    _ = _opt_str(inputs, "gcloud_bin")
    _ = _opt_str(inputs, "gcloud_runtime_config_dir")
    _ = _opt_str(inputs, "gcloud_active_account")
    _ = _opt_bool(inputs, "gcloud_copy_default_config")
    _ = _opt_str(inputs, "reverse_ssh_state_ref")
    required_env = inputs.get("required_env")
    if required_env is None:
        required_env = []
    if not isinstance(required_env, list):
        raise ModuleValidationError("inputs.required_env must be a list when set")
    normalized_required_env: list[str] = []
    for idx, item in enumerate(required_env, start=1):
        if not isinstance(item, str) or not item.strip():
            raise ModuleValidationError(f"inputs.required_env[{idx}] must be a non-empty string")
        normalized_required_env.append(item.strip())

    if apply_mode in ("establish", "status"):
        project_id = _opt_str(inputs, "project_id")
        if project_id and not _PROJECT_ID_RE.fullmatch(project_id):
            raise ModuleValidationError("inputs.project_id is not a valid GCP project id format")

        region = _req_str(inputs, "region")
        _reject_placeholder(region, "inputs.region")

        private_network = _opt_str(inputs, "private_network")
        if apply_mode == "establish" and not private_network and not _opt_str(inputs, "network_state_ref"):
            raise ModuleValidationError(
                "one of inputs.private_network or inputs.network_state_ref is required for apply_mode=establish"
            )

        source_profile = _req_str(inputs, "source_connection_profile_name")
        _reject_placeholder(source_profile, "inputs.source_connection_profile_name")
        if not _INSTANCE_NAME_RE.fullmatch(source_profile):
            raise ModuleValidationError(
                "inputs.source_connection_profile_name must match ^[a-z](?:[a-z0-9-]{0,96}[a-z0-9])?$"
            )

        destination_profile = _req_str(inputs, "destination_connection_profile_name")
        _reject_placeholder(destination_profile, "inputs.destination_connection_profile_name")
        if not _INSTANCE_NAME_RE.fullmatch(destination_profile):
            raise ModuleValidationError(
                "inputs.destination_connection_profile_name must match ^[a-z](?:[a-z0-9-]{0,96}[a-z0-9])?$"
            )

        migration_job = _req_str(inputs, "migration_job_name")
        _reject_placeholder(migration_job, "inputs.migration_job_name")
        if not _INSTANCE_NAME_RE.fullmatch(migration_job):
            raise ModuleValidationError(
                "inputs.migration_job_name must match ^[a-z](?:[a-z0-9-]{0,96}[a-z0-9])?$"
            )

        job_type = _req_str(inputs, "migration_job_type").upper()
        if job_type not in ("CONTINUOUS", "ONE_TIME"):
            raise ModuleValidationError("inputs.migration_job_type must be one of: CONTINUOUS, ONE_TIME")

        objects_mode = _req_str(inputs, "migration_objects_mode").lower()
        if objects_mode not in ("single-database", "all-databases"):
            raise ModuleValidationError(
                "inputs.migration_objects_mode must be one of: single-database, all-databases"
            )

        connectivity_mode = _req_str(inputs, "connectivity_mode").lower()
        if connectivity_mode not in ("static-ip", "peer-vpc", "reverse-ssh"):
            raise ModuleValidationError(
                "inputs.connectivity_mode must be one of: static-ip, peer-vpc, reverse-ssh"
            )

        ssl_type = _req_str(inputs, "source_ssl_type").upper()
        if ssl_type not in ("NONE", "REQUIRED", "SERVER_ONLY", "SERVER_CLIENT"):
            raise ModuleValidationError(
                "inputs.source_ssl_type must be one of: NONE, REQUIRED, SERVER_ONLY, SERVER_CLIENT"
            )
        source_ca_certificate_env = _opt_str(inputs, "source_ca_certificate_env")
        source_client_certificate_env = _opt_str(inputs, "source_client_certificate_env")
        source_private_key_env = _opt_str(inputs, "source_private_key_env")

        if ssl_type == "NONE":
            if (
                source_ca_certificate_env
                or source_client_certificate_env
                or source_private_key_env
            ):
                raise ModuleValidationError(
                    "inputs.source_ssl_type=NONE cannot be combined with TLS certificate env fields"
                )
        else:
            if not source_ca_certificate_env:
                raise ModuleValidationError(
                    "inputs.source_ca_certificate_env is required when inputs.source_ssl_type enables TLS"
                )
            if ssl_type == "SERVER_CLIENT":
                if not source_client_certificate_env:
                    raise ModuleValidationError(
                        "inputs.source_client_certificate_env is required when inputs.source_ssl_type=SERVER_CLIENT"
                    )
                if not source_private_key_env:
                    raise ModuleValidationError(
                        "inputs.source_private_key_env is required when inputs.source_ssl_type=SERVER_CLIENT"
                    )
            tls_env_keys = [
                key
                for key in (
                    source_ca_certificate_env,
                    source_client_certificate_env,
                    source_private_key_env,
                )
                if key
            ]
            missing_tls_env = [key for key in tls_env_keys if key not in normalized_required_env]
            if missing_tls_env:
                raise ModuleValidationError(
                    "inputs.required_env must include TLS env key(s): " + ", ".join(missing_tls_env)
                )

        if apply_mode == "establish":
            _req_str(inputs, "source_replication_user")
            source_replication_password_env = _req_str(inputs, "source_replication_password_env")
            if source_replication_password_env not in normalized_required_env:
                raise ModuleValidationError(
                    "inputs.required_env must include inputs.source_replication_password_env "
                    f"({source_replication_password_env}) for apply_mode=establish"
                )
            destination_root_password_env = _opt_str(inputs, "destination_root_password_env")
            if destination_root_password_env and destination_root_password_env not in normalized_required_env:
                raise ModuleValidationError(
                    "inputs.required_env must include inputs.destination_root_password_env "
                    f"({destination_root_password_env}) when it is set"
                )

            destination_database_version = _req_str(inputs, "destination_database_version").upper()
            if not destination_database_version.startswith("POSTGRES_"):
                raise ModuleValidationError(
                    "inputs.destination_database_version must be a supported PostgreSQL version token, e.g. POSTGRES_16"
                )

            destination_tier = _req_str(inputs, "destination_tier")
            _reject_placeholder(destination_tier, "inputs.destination_tier")

            destination_edition = _req_str(inputs, "destination_edition").upper()
            if destination_edition not in ("ENTERPRISE", "ENTERPRISE_PLUS"):
                raise ModuleValidationError(
                    "inputs.destination_edition must be one of: ENTERPRISE, ENTERPRISE_PLUS"
                )

            destination_availability_type = _req_str(inputs, "destination_availability_type").upper()
            if destination_availability_type not in ("ZONAL", "REGIONAL"):
                raise ModuleValidationError(
                    "inputs.destination_availability_type must be one of: ZONAL, REGIONAL"
                )

            if connectivity_mode == "reverse-ssh":
                reverse_ssh_state_ref = _opt_str(inputs, "reverse_ssh_state_ref")
                vm_name = _opt_str(inputs, "reverse_ssh_vm")
                vm_ip = _opt_str(inputs, "reverse_ssh_vm_ip")
                vm_zone = _opt_str(inputs, "reverse_ssh_vm_zone")
                if not reverse_ssh_state_ref and not (vm_name and vm_ip and vm_zone):
                    raise ModuleValidationError(
                        "for inputs.connectivity_mode=reverse-ssh, provide inputs.reverse_ssh_state_ref "
                        "or explicit inputs.reverse_ssh_vm, inputs.reverse_ssh_vm_ip, and inputs.reverse_ssh_vm_zone"
                    )
                if vm_name:
                    _req_str(inputs, "reverse_ssh_vm")
                if vm_ip:
                    _validate_ipv4(vm_ip, "inputs.reverse_ssh_vm_ip")
                if vm_zone:
                    _req_str(inputs, "reverse_ssh_vm_zone")
                vm_port = inputs.get("reverse_ssh_vm_port")
                if isinstance(vm_port, bool) or not isinstance(vm_port, int) or vm_port <= 0:
                    raise ModuleValidationError("inputs.reverse_ssh_vm_port must be a positive integer")
                if vm_port == 22:
                    raise ModuleValidationError(
                        "inputs.reverse_ssh_vm_port must be the reverse tunnel port on the bastion VM, not the SSH daemon port 22"
                    )
                if not _opt_str(inputs, "reverse_ssh_vpc") and not private_network and not _opt_str(inputs, "network_state_ref"):
                    raise ModuleValidationError(
                        "inputs.reverse_ssh_vpc or inputs.network_state_ref/private_network is required when inputs.connectivity_mode=reverse-ssh"
                    )
