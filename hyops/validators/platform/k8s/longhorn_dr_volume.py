"""
purpose: Validate inputs for platform/k8s/longhorn-dr-volume module.
maintainer: HybridOps.Tech
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from hyops.validators.registry import ModuleValidationError

_ALLOWED_MODES = {"observe", "standby", "restore", "activate"}
_ALLOWED_ACCESS_MODES = {"rwo", "rwop", "rwx"}
_ALLOWED_DATA_ENGINES = {"v1", "v2"}


def _req_str(inputs: dict[str, Any], key: str) -> str:
    value = inputs.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ModuleValidationError(f"inputs.{key} must be a non-empty string")
    token = value.strip()
    marker = token.upper()
    if marker.startswith("CHANGE_ME") or "CHANGE_ME_" in marker:
        raise ModuleValidationError(f"inputs.{key} must not contain placeholder values")
    return token


def _opt_str(inputs: dict[str, Any], key: str) -> str:
    value = inputs.get(key)
    if value is None:
        return ""
    if not isinstance(value, str):
        raise ModuleValidationError(f"inputs.{key} must be a string when set")
    token = value.strip()
    if not token:
        return ""
    marker = token.upper()
    if marker.startswith("CHANGE_ME") or "CHANGE_ME_" in marker:
        raise ModuleValidationError(f"inputs.{key} must not contain placeholder values")
    return token


def _req_bool_or_default(inputs: dict[str, Any], key: str) -> None:
    value = inputs.get(key)
    if value is not None and not isinstance(value, bool):
        raise ModuleValidationError(f"inputs.{key} must be a boolean")


def _req_int_ge(inputs: dict[str, Any], key: str, minimum: int) -> int:
    value = inputs.get(key)
    if isinstance(value, bool) or not isinstance(value, int):
        raise ModuleValidationError(f"inputs.{key} must be an integer")
    if value < minimum:
        raise ModuleValidationError(f"inputs.{key} must be >= {minimum}")
    return value


def _lifecycle(inputs: dict[str, Any]) -> str:
    return str(inputs.get("hyops_lifecycle_command") or inputs.get("_hyops_lifecycle_command") or "").strip().lower()


def validate(inputs: dict[str, Any]) -> None:
    lifecycle = _lifecycle(inputs)

    kubeconfig_path = _req_str(inputs, "kubeconfig_path")
    kubeconfig = Path(kubeconfig_path).expanduser()
    if not kubeconfig.exists():
        raise ModuleValidationError(
            f"inputs.kubeconfig_path must point to an existing file on the controller: {kubeconfig}"
        )
    if not kubeconfig.is_file():
        raise ModuleValidationError(
            f"inputs.kubeconfig_path must point to a file, not a directory: {kubeconfig}"
        )

    _req_str(inputs, "kubectl_bin")
    _req_str(inputs, "longhorn_namespace")

    restore_volume_name = _opt_str(inputs, "restore_volume_name")

    if lifecycle == "destroy":
        if not restore_volume_name:
            raise ModuleValidationError("inputs.restore_volume_name is required for destroy")
        return

    operation_mode = _req_str(inputs, "operation_mode").lower()
    if operation_mode not in _ALLOWED_MODES:
        allowed = ", ".join(sorted(_ALLOWED_MODES))
        raise ModuleValidationError(f"inputs.operation_mode must be one of: {allowed}")

    backup_name = _opt_str(inputs, "backup_name")
    backup_url = _opt_str(inputs, "backup_url")

    if operation_mode in {"observe", "standby", "restore"} and not (backup_name or backup_url):
        raise ModuleValidationError("inputs.backup_name or inputs.backup_url is required")

    if operation_mode in {"standby", "restore", "activate"} and not restore_volume_name:
        raise ModuleValidationError(
            f"inputs.restore_volume_name is required when inputs.operation_mode={operation_mode!r}"
        )

    access_mode = _req_str(inputs, "restore_access_mode").lower()
    if access_mode not in _ALLOWED_ACCESS_MODES:
        allowed = ", ".join(sorted(_ALLOWED_ACCESS_MODES))
        raise ModuleValidationError(f"inputs.restore_access_mode must be one of: {allowed}")

    data_engine = _req_str(inputs, "restore_data_engine").lower()
    if data_engine not in _ALLOWED_DATA_ENGINES:
        allowed = ", ".join(sorted(_ALLOWED_DATA_ENGINES))
        raise ModuleValidationError(f"inputs.restore_data_engine must be one of: {allowed}")

    _req_int_ge(inputs, "restore_number_of_replicas", 1)
    _req_int_ge(inputs, "wait_timeout_s", 5)
    _req_int_ge(inputs, "wait_poll_interval_s", 1)
    _req_bool_or_default(inputs, "wait_restore_complete")

    restore_size = _opt_str(inputs, "restore_size")
    if restore_size and not restore_size.isdigit():
        raise ModuleValidationError("inputs.restore_size must be an integer byte-count string when set")

    restore_labels = inputs.get("restore_labels")
    if restore_labels is not None:
        if not isinstance(restore_labels, dict):
            raise ModuleValidationError("inputs.restore_labels must be a mapping when set")
        for key, value in restore_labels.items():
            if not isinstance(key, str) or not key.strip():
                raise ModuleValidationError("inputs.restore_labels keys must be non-empty strings")
            if not isinstance(value, str):
                raise ModuleValidationError(
                    f"inputs.restore_labels.{key} must be a string because Kubernetes labels are string-valued"
                )
