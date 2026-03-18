"""
purpose: Validate inputs for platform/k8s/gsm-bootstrap module.
Architecture Decision: ADR-N/A (gsm-bootstrap validator)
maintainer: HybridOps
"""

from __future__ import annotations

from typing import Any

from hyops.validators.common import (
    check_no_placeholder,
    opt_str,
    require_non_empty_str,
)
from hyops.validators.registry import ModuleValidationError


def _req_str(inputs: dict[str, Any], key: str) -> str:
    return check_no_placeholder(
        require_non_empty_str(inputs.get(key), f"inputs.{key}"),
        f"inputs.{key}",
    )


def _opt_str(inputs: dict[str, Any], key: str) -> str:
    v = opt_str(inputs.get(key), f"inputs.{key}")
    return check_no_placeholder(v, f"inputs.{key}") if v else v


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
