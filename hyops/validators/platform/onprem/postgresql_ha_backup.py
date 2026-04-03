"""hyops.validators.platform.onprem.postgresql_ha_backup

purpose: Validate inputs for the PostgreSQL HA backup module.
maintainer: HybridOps.Tech
"""

from __future__ import annotations

import re
from typing import Any

from hyops.validators.common import (
    normalize_lifecycle_command,
    normalize_required_env,
    require_mapping,
    require_non_empty_str,
    require_port,
)


_AZURE_STORAGE_ACCOUNT_RE = re.compile(r"^[a-z0-9]{3,24}$")
_AZURE_CONTAINER_RE = re.compile(r"^[a-z0-9](?:[a-z0-9-]{1,61}[a-z0-9])?$")
_EXECUTION_PLANES = {"workstation-direct", "runner-local"}
_PGHA_STATE_REFS = {"platform/postgresql-ha", "platform/onprem/postgresql-ha"}


def _state_ref_publishes_inventory(raw_ref: Any) -> bool:
    ref = str(raw_ref or "").strip()
    if not ref:
        return False
    base = ref.split("#", 1)[0].strip().lower()
    return base in _PGHA_STATE_REFS
def _validate_inventory(data: dict[str, Any], *, lifecycle: str) -> None:
    inventory_groups = data.get("inventory_groups")
    inventory_state_ref = data.get("inventory_state_ref")
    inventory_vm_groups = data.get("inventory_vm_groups")
    required_groups = ["postgres_cluster"] if lifecycle == "destroy" else ["master", "replica", "postgres_cluster"]

    if inventory_groups is not None and not isinstance(inventory_groups, dict):
        raise ValueError("inputs.inventory_groups must be a mapping when set")

    if isinstance(inventory_groups, dict) and inventory_groups:
        groups = inventory_groups
    else:
        if inventory_state_ref is None or not isinstance(inventory_state_ref, str) or not inventory_state_ref.strip():
            raise ValueError(
                "inputs.inventory_state_ref is required when inputs.inventory_groups is empty "
                "(recommended: platform/onprem/platform-vm)"
            )
        if _state_ref_publishes_inventory(inventory_state_ref):
            groups = {group: ["placeholder"] for group in required_groups}
        elif inventory_vm_groups is None or not isinstance(inventory_vm_groups, dict) or not inventory_vm_groups:
            raise ValueError("inputs.inventory_vm_groups must be a non-empty mapping when inputs.inventory_state_ref is set")
        else:
            groups = inventory_vm_groups

    for g in required_groups:
        if g not in groups:
            raise ValueError(f"inventory must include group {g!r}")

    dcs_type = str(data.get("dcs_type") or "etcd").strip().lower() or "etcd"
    dcs_exists = bool(data.get("dcs_exists") or False)
    if lifecycle != "destroy" and dcs_type == "etcd" and not dcs_exists:
        if "etcd_cluster" not in groups:
            raise ValueError("inventory must include group 'etcd_cluster' when dcs_type=etcd and dcs_exists=false")

    if data.get("inventory_requires_ipam") is not None and not isinstance(data.get("inventory_requires_ipam"), bool):
        raise ValueError("inputs.inventory_requires_ipam must be a boolean when set")


def _normalize_backend(raw: Any, field_name: str) -> str:
    backend = str(raw or "").strip().lower()
    if backend == "gcp":
        backend = "gcs"
    if backend in ("azblob", "blob"):
        backend = "azure"
    if backend not in ("s3", "gcs", "azure"):
        raise ValueError(f"{field_name} must be one of: s3, gcs, azure")
    return backend


def _validate_backend_settings(data: dict[str, Any], *, backend: str, prefix: str = "") -> list[str]:
    if backend == "s3":
        require_non_empty_str(data.get(f"{prefix}s3_bucket"), f"inputs.{prefix}s3_bucket")
        access_key = require_non_empty_str(data.get(f"{prefix}s3_access_key_env"), f"inputs.{prefix}s3_access_key_env")
        secret_key = require_non_empty_str(data.get(f"{prefix}s3_secret_key_env"), f"inputs.{prefix}s3_secret_key_env")
        return [access_key, secret_key]

    if backend == "gcs":
        require_non_empty_str(data.get(f"{prefix}gcs_bucket"), f"inputs.{prefix}gcs_bucket")
        sa_env = require_non_empty_str(data.get(f"{prefix}gcs_sa_json_env"), f"inputs.{prefix}gcs_sa_json_env")
        require_non_empty_str(data.get(f"{prefix}gcs_sa_dest"), f"inputs.{prefix}gcs_sa_dest")
        return [sa_env]

    storage_account = require_non_empty_str(
        data.get(f"{prefix}azure_storage_account"), f"inputs.{prefix}azure_storage_account"
    )
    if not _AZURE_STORAGE_ACCOUNT_RE.fullmatch(storage_account):
        raise ValueError(f"inputs.{prefix}azure_storage_account must match ^[a-z0-9]{{3,24}}$")

    container = require_non_empty_str(data.get(f"{prefix}azure_container"), f"inputs.{prefix}azure_container").lower()
    if not _AZURE_CONTAINER_RE.fullmatch(container) or "--" in container:
        raise ValueError(
            f"inputs.{prefix}azure_container must match ^[a-z0-9](?:[a-z0-9-]{{1,61}}[a-z0-9])?$ and "
            "must not contain consecutive hyphens"
        )

    account_key = require_non_empty_str(
        data.get(f"{prefix}azure_account_key_env"), f"inputs.{prefix}azure_account_key_env"
    )
    return [account_key]


def validate(inputs: dict[str, Any]) -> None:
    data = require_mapping(inputs, "inputs")
    lifecycle = normalize_lifecycle_command(data)

    # Dependency guard: backup only makes sense once the HA cluster is ready.
    upstream_cap = str(data.get("upstream", {}).get("cap_db_postgresql_ha") if isinstance(data.get("upstream"), dict) else "")
    if lifecycle != "destroy" and upstream_cap.strip().lower() != "ready":
        raise ValueError("dependency platform/postgresql-ha is not ready (expected outputs.cap.db.postgresql_ha=ready)")

    apply_mode = str(data.get("apply_mode") or "").strip().lower()
    if apply_mode and apply_mode not in ("backup",):
        raise ValueError("inputs.apply_mode must be empty or 'backup'")

    _validate_inventory(data, lifecycle=lifecycle)

    # SSH defaults applied to every host in the inventory.
    execution_plane = str(data.get("execution_plane") or "workstation-direct").strip().lower() or "workstation-direct"
    if execution_plane not in _EXECUTION_PLANES:
        raise ValueError("inputs.execution_plane must be one of: workstation-direct, runner-local")

    require_non_empty_str(data.get("target_user"), "inputs.target_user")
    if data.get("target_port") is not None:
        require_port(data.get("target_port"), "inputs.target_port")

    if data.get("ssh_private_key_file") is not None and str(data.get("ssh_private_key_file") or "").strip() != "":
        require_non_empty_str(data.get("ssh_private_key_file"), "inputs.ssh_private_key_file")

    if data.get("ssh_proxy_jump_host") is not None and str(data.get("ssh_proxy_jump_host") or "").strip() != "":
        require_non_empty_str(data.get("ssh_proxy_jump_host"), "inputs.ssh_proxy_jump_host")
        if data.get("ssh_proxy_jump_user") is not None:
            require_non_empty_str(data.get("ssh_proxy_jump_user"), "inputs.ssh_proxy_jump_user")
        if data.get("ssh_proxy_jump_port") is not None:
            require_port(data.get("ssh_proxy_jump_port"), "inputs.ssh_proxy_jump_port")
    if data.get("ssh_proxy_jump_auto") is not None and not isinstance(data.get("ssh_proxy_jump_auto"), bool):
        raise ValueError("inputs.ssh_proxy_jump_auto must be a boolean when set")

    if data.get("become") is not None and not isinstance(data.get("become"), bool):
        raise ValueError("inputs.become must be a boolean when set")
    if data.get("become_user") is not None:
        require_non_empty_str(data.get("become_user"), "inputs.become_user")

    if lifecycle == "destroy":
        normalize_required_env(data.get("required_env_destroy"), "inputs.required_env_destroy")
        return

    backend = _normalize_backend(data.get("backend") or "s3", "inputs.backend")
    repo_mismatch_action = str(data.get("repo_mismatch_action") or "fail").strip().lower()
    if repo_mismatch_action not in ("fail", "reset"):
        raise ValueError("inputs.repo_mismatch_action must be one of: fail, reset")

    secondary_enabled_raw = data.get("secondary_enabled")
    if secondary_enabled_raw is not None and not isinstance(secondary_enabled_raw, bool):
        raise ValueError("inputs.secondary_enabled must be a boolean when set")
    secondary_enabled = bool(secondary_enabled_raw or False)
    secondary_backend = ""
    if secondary_enabled:
        secondary_backend = _normalize_backend(data.get("secondary_backend"), "inputs.secondary_backend")
        if data.get("secondary_repo_path") is not None:
            require_non_empty_str(data.get("secondary_repo_path"), "inputs.secondary_repo_path")

    primary_backend_env_keys = _validate_backend_settings(data, backend=backend, prefix="")
    secondary_backend_env_keys: list[str] = []
    if secondary_enabled:
        secondary_backend_env_keys = _validate_backend_settings(data, backend=secondary_backend, prefix="secondary_")

    # Enforce required_env includes platform DB auth keys and backend credential env keys.
    required_env = normalize_required_env(data.get("required_env"), "inputs.required_env")
    if not required_env:
        raise ValueError("inputs.required_env must be a non-empty list")

    must_have = ["PATRONI_SUPERUSER_PASSWORD", "PATRONI_REPLICATION_PASSWORD"]
    missing = [k for k in must_have if k not in required_env]
    if missing:
        raise ValueError("inputs.required_env must include: " + ", ".join(missing))

    backend_env_keys = [k for k in (primary_backend_env_keys + secondary_backend_env_keys) if k]
    missing_backend_env = [k for k in backend_env_keys if k not in required_env]
    if missing_backend_env:
        raise ValueError(
            "inputs.required_env must include backend credential env key(s): " + ", ".join(missing_backend_env)
        )

    # Optional retention/scheduling
    if data.get("retention_full") is not None:
        raw = data.get("retention_full")
        if isinstance(raw, bool) or not isinstance(raw, int):
            raise ValueError("inputs.retention_full must be an integer")
        if raw < 1:
            raise ValueError("inputs.retention_full must be >= 1")
    if data.get("backup_hour") is not None:
        raw_hour = data.get("backup_hour")
        if isinstance(raw_hour, bool) or not isinstance(raw_hour, int):
            raise ValueError("inputs.backup_hour must be an integer")
        if raw_hour < 0 or raw_hour > 23:
            raise ValueError("inputs.backup_hour must be between 0 and 23")
