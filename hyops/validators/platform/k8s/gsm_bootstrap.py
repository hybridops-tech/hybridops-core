"""
purpose: Validate inputs for platform/k8s/gsm-bootstrap module.
Architecture Decision: ADR-N/A (gsm-bootstrap validator)
maintainer: HybridOps
"""

from __future__ import annotations

from typing import Any

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


def validate(inputs: dict[str, Any]) -> None:
    raw_state_ref = str(inputs.get("kubeconfig_state_ref") or "").strip()
    raw_path = str(inputs.get("kubeconfig_path") or "").strip()
    if not raw_state_ref and not raw_path:
        raise ModuleValidationError("inputs.kubeconfig_path or inputs.kubeconfig_state_ref is required")
    if raw_state_ref:
        _req_str(inputs, "kubeconfig_state_ref")
    if raw_path:
        _req_str(inputs, "kubeconfig_path")

    _req_str(inputs, "eso_namespace")
    _req_str(inputs, "secret_name")
    _req_str(inputs, "secret_key")
    _req_str(inputs, "gsm_sa_key_json_env")

    value = inputs.get("connectivity_check")
    if value is not None and not isinstance(value, bool):
        raise ModuleValidationError("inputs.connectivity_check must be a boolean")
