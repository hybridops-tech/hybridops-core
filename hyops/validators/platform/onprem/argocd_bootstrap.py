"""hyops.validators.platform.onprem.argocd_bootstrap

purpose: Validate inputs for platform/onprem/argocd-bootstrap module.
Architecture Decision: ADR-N/A (onprem argocd-bootstrap validator)
maintainer: HybridOps.Studio
"""

from __future__ import annotations

import re
from typing import Any


_K8S_NAME_RE = re.compile(r"^[a-z0-9]([-a-z0-9]*[a-z0-9])?$")
_PATH_SEG_RE = re.compile(r"^[A-Za-z0-9._-]+$")


def _require_mapping(value: Any, field: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"{field} must be a mapping")
    return value


def _require_non_empty_str(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be a non-empty string")
    return value.strip()


def _require_bool(value: Any, field: str) -> bool:
    if not isinstance(value, bool):
        raise ValueError(f"{field} must be a boolean")
    return value


def _require_int_ge(value: Any, field: str, minimum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{field} must be an integer")
    if value < minimum:
        raise ValueError(f"{field} must be >= {minimum}")
    return value


def _validate_k8s_name(value: str, field: str) -> None:
    if len(value) > 63:
        raise ValueError(f"{field} must be <= 63 characters")
    if not _K8S_NAME_RE.fullmatch(value):
        raise ValueError(f"{field} must match Kubernetes DNS-1123 label format")


def _validate_repo_url(value: str, field: str) -> None:
    if "REPLACE_" in value:
        raise ValueError(f"{field} contains placeholder token; set a real Git URL")
    if value.startswith("https://") or value.startswith("http://"):
        return
    if value.startswith("ssh://"):
        return
    if value.startswith("git@") and ":" in value:
        return
    raise ValueError(
        f"{field} must be a valid Git URL (https://..., ssh://..., or git@host:org/repo.git)"
    )


def _validate_repo_path(value: str, field: str) -> None:
    if "REPLACE_" in value:
        raise ValueError(f"{field} contains placeholder token; set a real repo path")
    if value.startswith("/"):
        raise ValueError(f"{field} must be repo-relative (must not start with '/')")
    if "\\" in value:
        raise ValueError(f"{field} must use forward slashes")

    parts = [p for p in value.split("/") if p]
    if not parts:
        raise ValueError(f"{field} must be a non-empty repo-relative path")
    for idx, part in enumerate(parts, start=1):
        if part in (".", ".."):
            raise ValueError(f"{field} must not contain '.' or '..' segments")
        if not _PATH_SEG_RE.fullmatch(part):
            raise ValueError(f"{field} segment[{idx}] has unsupported characters: {part!r}")


def validate(inputs: dict[str, Any]) -> None:
    data = _require_mapping(inputs, "inputs")
    lifecycle = str(data.get("_hyops_lifecycle_command") or "").strip().lower()

    # Local inventory/driver behavior
    if data.get("connectivity_check") is not None:
        _require_bool(data.get("connectivity_check"), "inputs.connectivity_check")
    if data.get("install_argocd") is not None:
        _require_bool(data.get("install_argocd"), "inputs.install_argocd")
    if data.get("argocd_wait_ready") is not None:
        _require_bool(data.get("argocd_wait_ready"), "inputs.argocd_wait_ready")
    if data.get("sync_automated_prune") is not None:
        _require_bool(data.get("sync_automated_prune"), "inputs.sync_automated_prune")
    if data.get("sync_automated_self_heal") is not None:
        _require_bool(data.get("sync_automated_self_heal"), "inputs.sync_automated_self_heal")
    if data.get("create_namespace") is not None:
        _require_bool(data.get("create_namespace"), "inputs.create_namespace")
    if data.get("remove_argocd_namespace") is not None:
        _require_bool(data.get("remove_argocd_namespace"), "inputs.remove_argocd_namespace")

    if data.get("argocd_wait_timeout_s") is not None:
        _require_int_ge(data.get("argocd_wait_timeout_s"), "inputs.argocd_wait_timeout_s", 30)

    argocd_namespace = _require_non_empty_str(data.get("argocd_namespace"), "inputs.argocd_namespace")
    _validate_k8s_name(argocd_namespace, "inputs.argocd_namespace")

    root_app_name = _require_non_empty_str(data.get("root_app_name"), "inputs.root_app_name")
    _validate_k8s_name(root_app_name, "inputs.root_app_name")

    root_app_namespace = _require_non_empty_str(data.get("root_app_namespace"), "inputs.root_app_namespace")
    _validate_k8s_name(root_app_namespace, "inputs.root_app_namespace")

    _require_non_empty_str(data.get("root_app_project"), "inputs.root_app_project")

    root_destination_namespace = _require_non_empty_str(
        data.get("root_destination_namespace"), "inputs.root_destination_namespace"
    )
    _validate_k8s_name(root_destination_namespace, "inputs.root_destination_namespace")

    destination_server = _require_non_empty_str(data.get("destination_server"), "inputs.destination_server")
    if destination_server.startswith("REPLACE_"):
        raise ValueError("inputs.destination_server contains placeholder token")

    install_argocd = bool(data.get("install_argocd"))
    if install_argocd:
        manifest_url = _require_non_empty_str(
            data.get("argocd_install_manifest_url"), "inputs.argocd_install_manifest_url"
        )
        if "REPLACE_" in manifest_url:
            raise ValueError("inputs.argocd_install_manifest_url contains placeholder token")
        if not (manifest_url.startswith("https://") or manifest_url.startswith("http://")):
            raise ValueError("inputs.argocd_install_manifest_url must be http(s) URL")

    # Destroy can run with defaults and best-effort cleanup.
    if lifecycle == "destroy":
        return

    kubeconfig_path = _require_non_empty_str(data.get("kubeconfig_path"), "inputs.kubeconfig_path")
    if "REPLACE_" in kubeconfig_path:
        raise ValueError("inputs.kubeconfig_path contains placeholder token")

    workloads_repo_url = _require_non_empty_str(data.get("workloads_repo_url"), "inputs.workloads_repo_url")
    _validate_repo_url(workloads_repo_url, "inputs.workloads_repo_url")

    workloads_revision = _require_non_empty_str(data.get("workloads_revision"), "inputs.workloads_revision")
    if " " in workloads_revision:
        raise ValueError("inputs.workloads_revision must not contain spaces")
    if "REPLACE_" in workloads_revision:
        raise ValueError("inputs.workloads_revision contains placeholder token")

    workloads_target_path = _require_non_empty_str(data.get("workloads_target_path"), "inputs.workloads_target_path")
    _validate_repo_path(workloads_target_path, "inputs.workloads_target_path")
