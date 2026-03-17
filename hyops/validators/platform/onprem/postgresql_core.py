"""hyops.validators.platform.onprem.postgresql_core

purpose: Validate inputs for platform/onprem/postgresql-core module.
Architecture Decision: ADR-N/A (onprem postgresql-core validator)
maintainer: HybridOps.Tech
"""

from __future__ import annotations

import ipaddress
from typing import Any
import re


def _require_mapping(value: Any, field: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"{field} must be a mapping")
    return value


def _require_non_empty_str(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be a non-empty string")
    return value.strip()


def _require_port(value: Any, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{field} must be an integer")
    if value < 1 or value > 65535:
        raise ValueError(f"{field} must be between 1 and 65535")
    return value


def _require_str_list(value: Any, field: str) -> list[str]:
    if not isinstance(value, list):
        raise ValueError(f"{field} must be a list")
    out: list[str] = []
    for idx, item in enumerate(value, start=1):
        out.append(_require_non_empty_str(item, f"{field}[{idx}]"))
    if not out:
        raise ValueError(f"{field} must be a non-empty list")
    return out


def _validate_allowed_clients(value: Any) -> None:
    if value is None:
        return
    if not isinstance(value, list):
        raise ValueError("inputs.allowed_clients must be a list when set")

    for idx, item in enumerate(value, start=1):
        if not isinstance(item, dict):
            raise ValueError(f"inputs.allowed_clients[{idx}] must be a mapping")
        _require_non_empty_str(item.get("database"), f"inputs.allowed_clients[{idx}].database")
        _require_non_empty_str(item.get("user"), f"inputs.allowed_clients[{idx}].user")
        cidr = _require_non_empty_str(item.get("cidr"), f"inputs.allowed_clients[{idx}].cidr")
        try:
            _ = ipaddress.ip_network(cidr, strict=False)
        except Exception as exc:
            raise ValueError(f"inputs.allowed_clients[{idx}].cidr is invalid: {exc}") from exc


def _normalize_required_env(value: Any) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise ValueError("inputs.required_env must be a list when set")
    out: list[str] = []
    for idx, item in enumerate(value, start=1):
        out.append(_require_non_empty_str(item, f"inputs.required_env[{idx}]"))
    return out


_APP_KEY_RE = re.compile(r"^[a-zA-Z0-9_-]+$")


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

        app = _require_mapping(raw_app, f"inputs.apps.{key}")
        db_name = _require_non_empty_str(app.get("db_name"), f"inputs.apps.{key}.db_name")
        db_user = _require_non_empty_str(app.get("db_user"), f"inputs.apps.{key}.db_user")
        db_password_env = _require_non_empty_str(
            app.get("db_password_env"), f"inputs.apps.{key}.db_password_env"
        )
        out[key] = {
            "db_name": db_name,
            "db_user": db_user,
            "db_password_env": db_password_env,
        }

    return out


def validate(inputs: dict[str, Any]) -> None:
    data = _require_mapping(inputs, "inputs")

    _require_non_empty_str(data.get("target_host"), "inputs.target_host")

    if data.get("target_user") is not None:
        _require_non_empty_str(data.get("target_user"), "inputs.target_user")

    if data.get("target_port") is not None:
        _require_port(data.get("target_port"), "inputs.target_port")

    if data.get("ssh_private_key_file") is not None and str(data.get("ssh_private_key_file") or "").strip() != "":
        _require_non_empty_str(data.get("ssh_private_key_file"), "inputs.ssh_private_key_file")

    if data.get("become") is not None and not isinstance(data.get("become"), bool):
        raise ValueError("inputs.become must be a boolean when set")

    if data.get("become_user") is not None:
        _require_non_empty_str(data.get("become_user"), "inputs.become_user")

    if data.get("load_vault_env") is not None and not isinstance(data.get("load_vault_env"), bool):
        raise ValueError("inputs.load_vault_env must be a boolean when set")

    required_env = _normalize_required_env(data.get("required_env"))
    apps = _normalize_apps(data.get("apps"))

    if data.get("pg_port") is not None:
        _require_port(data.get("pg_port"), "inputs.pg_port")

    if data.get("listen_addresses") is not None:
        listen = _require_str_list(data.get("listen_addresses"), "inputs.listen_addresses")
        remote = [x for x in listen if x not in ("127.0.0.1", "localhost")]
        if remote and (not isinstance(data.get("allowed_clients"), list) or len(data.get("allowed_clients") or []) == 0):
            raise ValueError(
                "inputs.allowed_clients must be non-empty when inputs.listen_addresses includes non-local addresses"
            )

    _validate_allowed_clients(data.get("allowed_clients"))

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
        for app_key, app in apps.items():
            env_key = app.get("db_password_env") or ""
            if env_key not in required_env:
                missing.append(env_key)
        if missing:
            raise ValueError(
                "inputs.required_env must include: "
                + ", ".join(sorted(set(missing)))
                + " (required because inputs.apps.*.db_password_env references them)"
            )
        return

    # Legacy single-app contract
    _require_non_empty_str(data.get("db_name"), "inputs.db_name")
    _require_non_empty_str(data.get("db_user"), "inputs.db_user")
    db_password_env = _require_non_empty_str(data.get("db_password_env"), "inputs.db_password_env")

    if db_password_env not in required_env:
        raise ValueError(
            f"inputs.required_env must include: {db_password_env} (required because inputs.db_password_env references it)"
        )
