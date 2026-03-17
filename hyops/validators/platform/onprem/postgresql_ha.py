"""hyops.validators.platform.onprem.postgresql_ha

purpose: Validate inputs for the PostgreSQL HA module.
Architecture Decision: ADR-N/A (onprem postgresql-ha validator)
maintainer: HybridOps.Tech
"""

from __future__ import annotations

import ipaddress
import re
from typing import Any

from hyops.validators.common import (
    normalize_lifecycle_command,
    normalize_required_env,
    require_mapping,
    require_non_empty_str,
    require_port,
)


_APP_KEY_RE = re.compile(r"^[a-zA-Z0-9_-]+$")
_EXECUTION_PLANES = {"workstation-direct", "runner-local"}
_PGHA_STATE_REFS = {"platform/postgresql-ha", "platform/onprem/postgresql-ha"}


def _state_ref_publishes_inventory(raw_ref: Any) -> bool:
    ref = str(raw_ref or "").strip()
    if not ref:
        return False
    base = ref.split("#", 1)[0].strip().lower()
    return base in _PGHA_STATE_REFS


def _normalize_apps(value: Any) -> dict[str, dict[str, str]]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ValueError("inputs.apps must be a mapping when set")

    out: dict[str, dict[str, str]] = {}
    for raw_key, raw_app in value.items():
        if not isinstance(raw_key, str) or not raw_key.strip():
            raise ValueError("inputs.apps keys must be non-empty strings")
        key = raw_key.strip()
        if not _APP_KEY_RE.fullmatch(key):
            raise ValueError(f"inputs.apps key must match {_APP_KEY_RE.pattern}: {key!r}")

        app = require_mapping(raw_app, f"inputs.apps.{key}")
        db_name = require_non_empty_str(app.get("db_name"), f"inputs.apps.{key}.db_name")
        db_user = require_non_empty_str(app.get("db_user"), f"inputs.apps.{key}.db_user")
        db_password_env = require_non_empty_str(app.get("db_password_env"), f"inputs.apps.{key}.db_password_env")
        out[key] = {"db_name": db_name, "db_user": db_user, "db_password_env": db_password_env}

    return out


def _validate_allowed_clients(value: Any) -> None:
    if value is None:
        return
    if not isinstance(value, list):
        raise ValueError("inputs.allowed_clients must be a list when set")

    for idx, item in enumerate(value, start=1):
        if not isinstance(item, dict):
            raise ValueError(f"inputs.allowed_clients[{idx}] must be a mapping")
        require_non_empty_str(item.get("database"), f"inputs.allowed_clients[{idx}].database")
        require_non_empty_str(item.get("user"), f"inputs.allowed_clients[{idx}].user")
        cidr = require_non_empty_str(item.get("cidr"), f"inputs.allowed_clients[{idx}].cidr")
        try:
            _ = ipaddress.ip_network(cidr, strict=False)
        except Exception as exc:
            raise ValueError(f"inputs.allowed_clients[{idx}].cidr is invalid: {exc}") from exc


def _validate_pglogical_databases(value: Any) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise ValueError("inputs.pglogical_databases must be a list when set")

    out: list[str] = []
    seen: set[str] = set()
    for idx, item in enumerate(value, start=1):
        db_name = require_non_empty_str(item, f"inputs.pglogical_databases[{idx}]")
        if db_name in seen:
            raise ValueError(f"inputs.pglogical_databases contains duplicate value {db_name!r}")
        seen.add(db_name)
        out.append(db_name)
    return out


def _validate_inventory(data: dict[str, Any]) -> None:
    inventory_groups = data.get("inventory_groups")
    inventory_state_ref = data.get("inventory_state_ref")
    inventory_vm_groups = data.get("inventory_vm_groups")

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
            groups = {"master": ["placeholder"], "replica": ["placeholder"], "postgres_cluster": ["placeholder"]}
        elif inventory_vm_groups is None or not isinstance(inventory_vm_groups, dict) or not inventory_vm_groups:
            raise ValueError("inputs.inventory_vm_groups must be a non-empty mapping when inputs.inventory_state_ref is set")
        else:
            groups = inventory_vm_groups

    required_groups = ["master", "replica", "postgres_cluster"]
    for g in required_groups:
        if g not in groups:
            raise ValueError(f"inventory must include group {g!r}")

    dcs_type = str(data.get("dcs_type") or "etcd").strip().lower() or "etcd"
    dcs_exists = bool(data.get("dcs_exists") or False)
    if dcs_type == "etcd" and not dcs_exists:
        if "etcd_cluster" not in groups:
            raise ValueError("inventory must include group 'etcd_cluster' when dcs_type=etcd and dcs_exists=false")

    if data.get("inventory_requires_ipam") is not None and not isinstance(data.get("inventory_requires_ipam"), bool):
        raise ValueError("inputs.inventory_requires_ipam must be a boolean when set")


def validate(inputs: dict[str, Any]) -> None:
    data = require_mapping(inputs, "inputs")

    lifecycle = normalize_lifecycle_command(data)

    apply_mode = str(data.get("apply_mode") or "auto").strip().lower() or "auto"
    if apply_mode not in ("auto", "bootstrap", "maintenance", "restore"):
        raise ValueError("inputs.apply_mode must be one of: auto, bootstrap, maintenance, restore")

    # This module is on-prem only; Autobase cloud provisioning is out-of-scope.
    # Keep these empty so Autobase won't attempt to manage cloud resources.
    for field in ("cloud_provider", "provision"):
        raw = data.get(field)
        if raw is None:
            continue
        if not isinstance(raw, str):
            raise ValueError(f"inputs.{field} must be a string when set")
        if raw.strip() != "":
            raise ValueError(f"inputs.{field} must be empty for the PostgreSQL HA module")

    _validate_inventory(data)

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

    if data.get("connectivity_check") is not None and not isinstance(data.get("connectivity_check"), bool):
        raise ValueError("inputs.connectivity_check must be a boolean when set")
    if data.get("connectivity_timeout_s") is not None:
        raw_timeout = data.get("connectivity_timeout_s")
        if isinstance(raw_timeout, bool) or not isinstance(raw_timeout, int):
            raise ValueError("inputs.connectivity_timeout_s must be an integer")
        if raw_timeout < 1:
            raise ValueError("inputs.connectivity_timeout_s must be >= 1")
    if data.get("connectivity_wait_s") is not None:
        raw_wait = data.get("connectivity_wait_s")
        if isinstance(raw_wait, bool) or not isinstance(raw_wait, int):
            raise ValueError("inputs.connectivity_wait_s must be an integer")
        if raw_wait < 0:
            raise ValueError("inputs.connectivity_wait_s must be >= 0")

    if data.get("load_vault_env") is not None and not isinstance(data.get("load_vault_env"), bool):
        raise ValueError("inputs.load_vault_env must be a boolean when set")

    pg_version_raw = data.get("postgresql_version")
    if pg_version_raw is not None:
        if isinstance(pg_version_raw, bool) or not isinstance(pg_version_raw, int):
            raise ValueError("inputs.postgresql_version must be an integer")
        if pg_version_raw < 10:
            raise ValueError("inputs.postgresql_version must be >= 10")

    if data.get("postgresql_port") is not None:
        require_port(data.get("postgresql_port"), "inputs.postgresql_port")

    cluster_vip = str(data.get("cluster_vip") or "").strip()
    if cluster_vip:
        try:
            ip = ipaddress.ip_address(cluster_vip)
        except Exception as exc:
            raise ValueError(f"inputs.cluster_vip is invalid: {exc}") from exc
        if not isinstance(ip, ipaddress.IPv4Address):
            raise ValueError("inputs.cluster_vip must be IPv4")

    if data.get("with_haproxy_load_balancing") is not None and not isinstance(data.get("with_haproxy_load_balancing"), bool):
        raise ValueError("inputs.with_haproxy_load_balancing must be a boolean when set")

    if data.get("pgbouncer_install") is not None and not isinstance(data.get("pgbouncer_install"), bool):
        raise ValueError("inputs.pgbouncer_install must be a boolean when set")
    if data.get("netdata_install") is not None and not isinstance(data.get("netdata_install"), bool):
        raise ValueError("inputs.netdata_install must be a boolean when set")
    if data.get("pending_restart") is not None and not isinstance(data.get("pending_restart"), bool):
        raise ValueError("inputs.pending_restart must be a boolean when set")
    if data.get("pglogical_enable") is not None and not isinstance(data.get("pglogical_enable"), bool):
        raise ValueError("inputs.pglogical_enable must be a boolean when set")

    pglogical_databases = _validate_pglogical_databases(data.get("pglogical_databases"))

    _validate_allowed_clients(data.get("allowed_clients"))

    if bool(data.get("pglogical_enable")):
        if apply_mode != "maintenance":
            raise ValueError(
                "inputs.pglogical_enable is currently supported only with inputs.apply_mode=maintenance "
                "(it performs a day-2 source-posture reconcile on an existing cluster)"
            )
        if not bool(data.get("pending_restart")):
            raise ValueError(
                "inputs.pending_restart must be true when inputs.pglogical_enable=true "
                "(pglogical requires a controlled PostgreSQL restart after updating shared_preload_libraries)"
            )
        # Explicit pglogical_databases is optional; when omitted the wrapper uses
        # the normalized application contract (for example the netbox database).
        _ = pglogical_databases

    required_env = normalize_required_env(data.get("required_env"), "inputs.required_env")

    patroni_superuser_password_env = require_non_empty_str(
        data.get("patroni_superuser_password_env"), "inputs.patroni_superuser_password_env"
    )
    patroni_replication_password_env = require_non_empty_str(
        data.get("patroni_replication_password_env"), "inputs.patroni_replication_password_env"
    )

    missing_env_refs = [
        k
        for k in (patroni_superuser_password_env, patroni_replication_password_env)
        if k not in required_env
    ]
    if missing_env_refs and lifecycle != "destroy":
        raise ValueError(
            "inputs.required_env must include: "
            + ", ".join(missing_env_refs)
            + " (required because patroni password env keys reference them)"
        )

    if apply_mode == "restore" and lifecycle != "destroy":
        if not isinstance(data.get("restore_confirm"), bool) or not bool(data.get("restore_confirm")):
            raise ValueError(
                "inputs.restore_confirm must be true when inputs.apply_mode=restore "
                "(refusing to run a destructive restore without explicit confirmation)"
            )
        backup_state_ref = str(data.get("backup_state_ref") or "").strip()
        restore_set = str(data.get("restore_set") or "").strip()
        restore_target_time = str(data.get("restore_target_time") or "").strip()
        if not (backup_state_ref or restore_set or restore_target_time):
            raise ValueError(
                "restore mode requires an explicit recovery selector. Set one of: "
                "inputs.backup_state_ref, inputs.restore_set, or inputs.restore_target_time"
            )

        backend_raw = str(data.get("backend") or "").strip().lower()
        backend = "gcs" if backend_raw in ("gcs", "gcp") else "s3" if backend_raw == "s3" else ""
        if not backend:
            raise ValueError("inputs.backend is required for apply_mode=restore and must be one of: s3, gcs")

        require_non_empty_str(data.get("repo_path"), "inputs.repo_path")

        if backend == "s3":
            require_non_empty_str(data.get("s3_bucket"), "inputs.s3_bucket")
            s3_access_key_env = require_non_empty_str(data.get("s3_access_key_env"), "inputs.s3_access_key_env")
            s3_secret_key_env = require_non_empty_str(data.get("s3_secret_key_env"), "inputs.s3_secret_key_env")

        if backend == "gcs":
            require_non_empty_str(data.get("gcs_bucket"), "inputs.gcs_bucket")
            gcs_sa_json_env = require_non_empty_str(data.get("gcs_sa_json_env"), "inputs.gcs_sa_json_env")
            require_non_empty_str(data.get("gcs_sa_dest"), "inputs.gcs_sa_dest")

        # Fail fast: ensure hyops preflight validates repo credentials are present.
        missing_backup_env: list[str] = []
        if backend == "s3":
            for k in (s3_access_key_env, s3_secret_key_env):
                if k not in required_env:
                    missing_backup_env.append(k)
        if backend == "gcs":
            if gcs_sa_json_env not in required_env:
                missing_backup_env.append(gcs_sa_json_env)
        if missing_backup_env:
            raise ValueError(
                "inputs.required_env must include: "
                + ", ".join(missing_backup_env)
                + " (required for apply_mode=restore so hyops preflight can validate repo credentials)"
            )

        if restore_target_time:
            if "\n" in restore_target_time or "\r" in restore_target_time:
                raise ValueError("inputs.restore_target_time must not contain newlines")
            if "'" in restore_target_time:
                raise ValueError("inputs.restore_target_time must not contain single quotes")

        if restore_set:
            if "\n" in restore_set or "\r" in restore_set:
                raise ValueError("inputs.restore_set must not contain newlines")
            if any(ch.isspace() for ch in restore_set):
                raise ValueError("inputs.restore_set must not contain whitespace")

        restore_target_timeline = str(data.get("restore_target_timeline") or "").strip().lower()
        if restore_target_timeline:
            if restore_target_timeline not in {"current", "latest"} and not restore_target_timeline.isdigit():
                raise ValueError(
                    "inputs.restore_target_timeline must be a numeric timeline, 'current', or 'latest'"
                )

        if data.get("restore_delta") is not None and not isinstance(data.get("restore_delta"), bool):
            raise ValueError("inputs.restore_delta must be a boolean when set")

    apps = _normalize_apps(data.get("apps"))

    if apps:
        seen_db: dict[str, str] = {}
        seen_user: dict[str, str] = {}
        for app_key, app in apps.items():
            db_name = str(app.get("db_name") or "").strip()
            db_user = str(app.get("db_user") or "").strip()
            if db_name in seen_db and seen_db[db_name] != app_key:
                raise ValueError(
                    f"inputs.apps has duplicate db_name={db_name!r} (used by {seen_db[db_name]!r} and {app_key!r})"
                )
            if db_user in seen_user and seen_user[db_user] != app_key:
                raise ValueError(
                    f"inputs.apps has duplicate db_user={db_user!r} (used by {seen_user[db_user]!r} and {app_key!r})"
                )
            seen_db[db_name] = app_key
            seen_user[db_user] = app_key

        missing: list[str] = []
        for _, app in apps.items():
            env_key = app.get("db_password_env") or ""
            if env_key not in required_env:
                missing.append(env_key)
        if missing and lifecycle != "destroy":
            raise ValueError(
                "inputs.required_env must include: "
                + ", ".join(sorted(set(missing)))
                + " (required because inputs.apps.*.db_password_env references them)"
            )
        return

    # Legacy single-app contract
    require_non_empty_str(data.get("db_name"), "inputs.db_name")
    require_non_empty_str(data.get("db_user"), "inputs.db_user")
    db_password_env = require_non_empty_str(data.get("db_password_env"), "inputs.db_password_env")

    if lifecycle != "destroy" and db_password_env not in required_env:
        raise ValueError(
            f"inputs.required_env must include: {db_password_env} (required because inputs.db_password_env references it)"
        )
