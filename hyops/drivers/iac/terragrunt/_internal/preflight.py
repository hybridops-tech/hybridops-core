"""Terragrunt driver preflight helpers (internal)."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from typing import Any

from hyops.runtime.coerce import as_int
from hyops.runtime.module_state import read_module_state
from hyops.runtime.terraform_cloud import preflight_cloud_backend

from .netbox import hydrate_netbox_env, netbox_state_status


def _resolve_gke_project_id(*, runtime_root: Path, inputs: dict[str, Any]) -> str:
    direct = str(
        inputs.get("project_id")
        or inputs.get("network_project_id")
        or ""
    ).strip()
    if direct:
        return direct

    state_ref = str(inputs.get("project_state_ref") or "").strip()
    if not state_ref:
        return ""

    try:
        state = read_module_state(runtime_root / "state", state_ref)
    except Exception:
        return ""

    outputs = state.get("outputs")
    if not isinstance(outputs, dict):
        return ""
    return str(outputs.get("project_id") or "").strip()


def _preflight_gke_default_compute_sa(
    *,
    runtime_root: Path,
    env: dict[str, str],
    inputs: dict[str, Any],
) -> str:
    project_id = _resolve_gke_project_id(runtime_root=runtime_root, inputs=inputs)
    if not project_id:
        return ""

    try:
        project_number = subprocess.run(
            [
                "gcloud",
                "projects",
                "describe",
                project_id,
                "--format=value(projectNumber)",
            ],
            check=True,
            capture_output=True,
            text=True,
            env=env,
        ).stdout.strip()
    except Exception:
        return ""

    if not project_number:
        return ""

    default_sa = f"{project_number}-compute@developer.gserviceaccount.com"
    try:
        raw = subprocess.run(
            [
                "gcloud",
                "iam",
                "service-accounts",
                "describe",
                default_sa,
                "--project",
                project_id,
                "--format=json",
            ],
            check=True,
            capture_output=True,
            text=True,
            env=env,
        ).stdout
        payload = json.loads(raw or "{}")
    except Exception:
        return ""

    if bool(payload.get("disabled")):
        return (
            "GKE cluster preflight failed: the project default Compute Engine "
            f"service account is disabled: {default_sa}. "
            "GKE still requires it during cluster creation even when a separate "
            "node service account is configured. "
            f"Enable it first with: gcloud iam service-accounts enable {default_sa} "
            f"--project {project_id}"
        )
    return ""


def run_preflight_phase(
    *,
    command_name: str,
    result: dict[str, Any],
    policy_defaults: dict[str, Any],
    runtime_root: Path,
    backend_mode: str,
    env: dict[str, str],
    env_name: str,
    export_infra_hook: dict[str, Any] | None,
    contract: Any,
    module_ref: str,
    runtime: dict[str, Any],
    profile_ref: str,
    pack_id: str,
    required_credentials: list[str],
    inputs: dict[str, Any],
) -> tuple[bool, str]:
    """Execute preflight-only checks.

    Returns (handled, error_message). When handled and no error, caller should
    write result json and return success immediately.
    """
    if command_name != "preflight":
        return False, ""

    # Guard against late failures during terraform init/provider installs.
    min_free_disk_mb = max(0, int(as_int(policy_defaults.get("min_free_disk_mb"), default=256)))
    if min_free_disk_mb:
        try:
            free_mb = int(shutil.disk_usage(str(runtime_root)).free // (1024 * 1024))
        except Exception:
            free_mb = -1
        if free_mb >= 0 and free_mb < min_free_disk_mb:
            return True, (
                f"insufficient disk space under runtime root: free={free_mb}MB "
                f"required>={min_free_disk_mb}MB ({runtime_root})"
            )

    if backend_mode == "cloud":
        tfc_error = preflight_cloud_backend(env=env, runtime_root=runtime_root, env_name=env_name)
        if tfc_error:
            return True, tfc_error

    if module_ref == "platform/gcp/gke-cluster":
        gke_default_sa_error = _preflight_gke_default_compute_sa(
            runtime_root=runtime_root,
            env=env,
            inputs=inputs,
        )
        if gke_default_sa_error:
            return True, gke_default_sa_error

    state_root_raw = str(runtime.get("state_dir") or "").strip()
    credentials_dir_raw = str(runtime.get("credentials_dir") or "").strip()
    state_instance = str(runtime.get("state_instance") or "").strip() or None
    allow_state_drift_recreate = bool(runtime.get("allow_state_drift_recreate"))
    if state_root_raw:
        skip_status, skip_detail = contract.evaluate_state_skip(
            command_name=command_name,
            module_ref=module_ref,
            state_root=Path(state_root_raw).expanduser().resolve(),
            state_instance=state_instance,
            credentials_dir=(
                Path(credentials_dir_raw).expanduser().resolve()
                if credentials_dir_raw
                else None
            ),
            runtime_root=runtime_root,
            env=env,
        )
        if skip_status == "error":
            return True, skip_detail or "live state verification failed"
        if skip_status == "stale":
            if allow_state_drift_recreate:
                result["warnings"].append(
                    "live infrastructure drift detected for existing module state; "
                    "preflight is allowing recreate because blueprint state-skip verification is enabled: "
                    + (skip_detail or module_ref)
                )
                skip_status = "safe"
            else:
                return True, (
                    "live infrastructure drift detected for existing module state: "
                    + (skip_detail or module_ref)
                )

    if export_infra_hook and bool(export_infra_hook.get("push_to_netbox")):
        strict_netbox = bool(export_infra_hook.get("strict"))

        contract_error = contract.validate_push_to_netbox(
            command_name=command_name,
            module_ref=module_ref,
            runtime=runtime if isinstance(runtime, dict) else {},
        )
        if contract_error:
            if strict_netbox:
                return True, contract_error
            result["warnings"].append(f"push_to_netbox disabled (non-strict): {contract_error}")

        hydrate_warnings, missing = hydrate_netbox_env(env, runtime_root)
        if hydrate_warnings:
            result["warnings"].extend(hydrate_warnings)

        if missing:
            missing_str = ", ".join(missing)
            nb_state = netbox_state_status(runtime_root)
            hint = f"push_to_netbox preflight failed: missing required env vars: {missing_str}. "
            hint += "Provide them via shell env, credentials/netbox.env under the runtime root, or the runtime vault. "
            if "NETBOX_API_TOKEN" in missing:
                vault_file = (runtime_root / "vault" / "bootstrap.vault.env").resolve()
                env_hint = env_name or "<env>"
                hint += f"Generate a token value (length<=40) via: hyops secrets ensure --env {env_hint} NETBOX_API_TOKEN. "
                hint += f"(vault: {vault_file}) "
            if "NETBOX_API_URL" in missing and nb_state and nb_state not in ("ok", "ready"):
                hint += f"NetBox module state platform/onprem/netbox is not ready (status={nb_state}); apply it to publish netbox_api_url. "
            if strict_netbox:
                return True, hint.strip()
            result["warnings"].append(
                f"push_to_netbox disabled (non-strict): missing env vars: {missing_str}"
            )

    result["status"] = "ok"
    result["normalized_outputs"] = {
        "preflight": {
            "module_ref": module_ref,
            "profile_ref": profile_ref,
            "pack_id": pack_id,
            "required_credentials": required_credentials,
            "effective_zone_name": str(inputs.get("zone_name") or ""),
        }
    }
    return True, ""
