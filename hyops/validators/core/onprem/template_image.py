"""
purpose: Validate inputs for core/onprem/template-image module.
Architecture Decision: ADR-N/A (onprem template-image validator)
maintainer: HybridOps.Tech
"""

from __future__ import annotations

from typing import Any


_WINDOWS_TEMPLATE_KEYS = {
    "windows-server-2022",
    "windows-server-2025",
    "windows-11-enterprise",
}
_LINUX_TEMPLATE_KEYS = {
    "ubuntu-22.04",
    "ubuntu-24.04",
    "rocky-9",
    "rocky-10",
}
_ALL_TEMPLATE_KEYS = _WINDOWS_TEMPLATE_KEYS | _LINUX_TEMPLATE_KEYS


def _require_non_empty_str(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be a non-empty string")
    return value.strip()


def _require_positive_int(value: Any, field: str) -> int:
    if isinstance(value, bool):
        raise ValueError(f"{field} is required and must be a positive integer")
    if isinstance(value, int):
        if value <= 0:
            raise ValueError(f"{field} must be a positive integer")
        return value
    if isinstance(value, str):
        token = value.strip()
        if not token:
            raise ValueError(f"{field} is required and must be a positive integer")
        try:
            parsed = int(token)
        except Exception as exc:
            raise ValueError(f"{field} must be a positive integer") from exc
        if parsed <= 0:
            raise ValueError(f"{field} must be a positive integer")
        return parsed
    raise ValueError(f"{field} is required and must be a positive integer")


def _optional_non_negative_int(value: Any, field: str) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool):
        raise ValueError(f"{field} must be a non-negative integer")
    if isinstance(value, int):
        if value < 0:
            raise ValueError(f"{field} must be a non-negative integer")
        return value
    if isinstance(value, str):
        token = value.strip()
        if not token:
            return None
        try:
            parsed = int(token)
        except Exception as exc:
            raise ValueError(f"{field} must be a non-negative integer") from exc
        if parsed < 0:
            raise ValueError(f"{field} must be a non-negative integer")
        return parsed
    raise ValueError(f"{field} must be a non-negative integer")


def validate(inputs: dict[str, Any]) -> None:
    if not isinstance(inputs, dict):
        raise ValueError("inputs must be a mapping")

    template_key = _require_non_empty_str(inputs.get("template_key"), "inputs.template_key").lower()
    if template_key not in _ALL_TEMPLATE_KEYS:
        options = ", ".join(sorted(_ALL_TEMPLATE_KEYS))
        raise ValueError(f"inputs.template_key is invalid: {template_key!r} (supported: {options})")

    _optional_non_negative_int(inputs.get("vmid"), "inputs.vmid")

    name = inputs.get("name")
    if name is not None:
        _require_non_empty_str(name, "inputs.name")

    description = inputs.get("description")
    if description is not None and not isinstance(description, str):
        raise ValueError("inputs.description must be a string when set")

    pool = inputs.get("pool")
    if pool is not None and not isinstance(pool, str):
        raise ValueError("inputs.pool must be a string when set")

    for key in ("cpu_cores", "cpu_sockets", "memory_mb", "disk_size_gb"):
        value = inputs.get(key)
        if value is None:
            continue
        _require_positive_int(value, f"inputs.{key}")

    os_type = None
    communicator = None
    for key in ("disk_format", "cpu_type", "os_type", "network_bridge", "communicator", "ssh_username"):
        value = inputs.get(key)
        if value is None:
            continue
        parsed = _require_non_empty_str(value, f"inputs.{key}")
        if key == "os_type":
            os_type = parsed.lower()
        elif key == "communicator":
            communicator = parsed.lower()

    if template_key in _WINDOWS_TEMPLATE_KEYS:
        if communicator is not None and communicator != "winrm":
            raise ValueError(
                f"inputs.communicator={communicator!r} is incompatible with template_key={template_key!r}; use 'winrm'"
            )
        if os_type is not None and os_type not in ("win10", "win11"):
            raise ValueError(
                f"inputs.os_type={os_type!r} is incompatible with template_key={template_key!r}; use 'win10' or 'win11'"
            )

    if template_key in _LINUX_TEMPLATE_KEYS:
        if communicator is not None and communicator != "ssh":
            raise ValueError(
                f"inputs.communicator={communicator!r} is incompatible with template_key={template_key!r}; use 'ssh'"
            )
        if os_type is not None and os_type != "l26":
            raise ValueError(
                f"inputs.os_type={os_type!r} is incompatible with template_key={template_key!r}; use 'l26'"
            )

    admin_user = inputs.get("admin_user")
    if admin_user is not None:
        _require_non_empty_str(admin_user, "inputs.admin_user")

    rebuild_if_exists = inputs.get("rebuild_if_exists")
    if rebuild_if_exists is not None and not isinstance(rebuild_if_exists, bool):
        raise ValueError("inputs.rebuild_if_exists must be a boolean when set")
