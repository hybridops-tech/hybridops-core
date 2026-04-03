"""
purpose: Validate inputs for platform/gcp/gke-kubeconfig module.
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
    raw_cluster_state_ref = str(inputs.get("cluster_state_ref") or "").strip()
    if raw_cluster_state_ref:
        _req_str(inputs, "cluster_state_ref")
    else:
        _req_str(inputs, "project_id")
        _req_str(inputs, "location")
        _req_str(inputs, "cluster_name")

    if inputs.get("gcloud_copy_default_config") is not None and not isinstance(
        inputs.get("gcloud_copy_default_config"), bool
    ):
        raise ModuleValidationError("inputs.gcloud_copy_default_config must be a boolean")
    if inputs.get("use_internal_ip") is not None and not isinstance(inputs.get("use_internal_ip"), bool):
        raise ModuleValidationError("inputs.use_internal_ip must be a boolean")

    _req_str(inputs, "gcloud_bin")
    if str(inputs.get("kubeconfig_name") or "").strip():
        _req_str(inputs, "kubeconfig_name")
    if str(inputs.get("kubeconfig_path") or "").strip():
        _req_str(inputs, "kubeconfig_path")
    if str(inputs.get("gcloud_active_account") or "").strip():
        _req_str(inputs, "gcloud_active_account")
