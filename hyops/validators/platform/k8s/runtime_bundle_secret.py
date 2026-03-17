"""
purpose: Validate inputs for platform/k8s/runtime-bundle-secret module.
Architecture Decision: ADR-N/A (runtime-bundle-secret validator)
maintainer: HybridOps
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from hyops.validators.common import normalize_lifecycle_command
from hyops.validators.registry import ModuleValidationError


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
def validate(inputs: dict[str, Any]) -> None:
    lifecycle = normalize_lifecycle_command(inputs)

    raw_kube_state_ref = _opt_str(inputs, "kubeconfig_state_ref")
    raw_kube_path = _opt_str(inputs, "kubeconfig_path")
    if not raw_kube_state_ref and not raw_kube_path:
        raise ModuleValidationError("inputs.kubeconfig_path or inputs.kubeconfig_state_ref is required")

    _req_str(inputs, "namespace")
    _req_str(inputs, "secret_name")
    _req_str(inputs, "bundle_key")
    _req_str(inputs, "kubectl_bin")

    ensure_namespace = inputs.get("ensure_namespace")
    if ensure_namespace is not None and not isinstance(ensure_namespace, bool):
        raise ModuleValidationError("inputs.ensure_namespace must be a boolean")

    if lifecycle == "destroy":
        return

    bundle_source_path = _req_str(inputs, "bundle_source_path")
    bundle_path = Path(bundle_source_path).expanduser()
    if not bundle_path.exists():
        raise ModuleValidationError(
            f"inputs.bundle_source_path must point to an existing file on the controller: {bundle_path}"
        )
    if not bundle_path.is_file():
        raise ModuleValidationError(
            f"inputs.bundle_source_path must point to a file, not a directory: {bundle_path}"
        )
