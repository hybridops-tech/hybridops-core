"""
purpose: Validate inputs for platform/k8s/gcp-secret-store module.
Architecture Decision: ADR-N/A (gcp-secret-store validator)
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


def _lifecycle(inputs: dict[str, Any]) -> str:
    return str(inputs.get("hyops_lifecycle_command") or inputs.get("_hyops_lifecycle_command") or "").strip().lower()


def validate(inputs: dict[str, Any]) -> None:
    lifecycle = _lifecycle(inputs)

    raw_kube_state_ref = _opt_str(inputs, "kubeconfig_state_ref")
    raw_kube_path = _opt_str(inputs, "kubeconfig_path")
    if not raw_kube_state_ref and not raw_kube_path:
        raise ModuleValidationError("inputs.kubeconfig_path or inputs.kubeconfig_state_ref is required")

    raw_cluster_state_ref = _opt_str(inputs, "cluster_state_ref")
    explicit_project = _opt_str(inputs, "project_id")
    explicit_location = _opt_str(inputs, "location")
    explicit_cluster = _opt_str(inputs, "cluster_name")
    if lifecycle == "destroy":
        if not raw_cluster_state_ref and not explicit_project:
            raise ModuleValidationError(
                "inputs.cluster_state_ref or explicit inputs.project_id is required for destroy"
            )
    elif not raw_cluster_state_ref and not (explicit_project and explicit_location and explicit_cluster):
        raise ModuleValidationError(
            "inputs.cluster_state_ref or explicit inputs.project_id, inputs.location, and inputs.cluster_name are required"
        )

    _req_str(inputs, "eso_namespace")
    _req_str(inputs, "service_account_namespace")
    _req_str(inputs, "service_account_name")
    _req_str(inputs, "secret_store_name")
    _req_str(inputs, "iam_role")
    _req_str(inputs, "kubectl_bin")
    _req_str(inputs, "gcloud_bin")
    _opt_str(inputs, "secret_project_id")

    ensure_secretmanager_api = inputs.get("ensure_secretmanager_api")
    if ensure_secretmanager_api is not None and not isinstance(ensure_secretmanager_api, bool):
        raise ModuleValidationError("inputs.ensure_secretmanager_api must be a boolean")
    ensure_eso_crds = inputs.get("ensure_eso_crds")
    if ensure_eso_crds is not None and not isinstance(ensure_eso_crds, bool):
        raise ModuleValidationError("inputs.ensure_eso_crds must be a boolean")
    _req_str(inputs, "eso_crds_bundle_url")

    wait_timeout_s = inputs.get("wait_timeout_s")
    if wait_timeout_s is None or isinstance(wait_timeout_s, bool) or not isinstance(wait_timeout_s, int):
        raise ModuleValidationError("inputs.wait_timeout_s must be an integer")
    if wait_timeout_s <= 0:
        raise ModuleValidationError("inputs.wait_timeout_s must be greater than zero")
