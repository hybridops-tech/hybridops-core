"""Terragrunt driver preflight helpers (internal)."""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any

from hyops.runtime.coerce import as_int
from hyops.runtime.credentials import parse_tfvars
from hyops.runtime.gcp import diagnose_project_billing
from hyops.runtime.module_state import read_module_state
from hyops.runtime.terraform_cloud import preflight_cloud_backend

from .netbox import hydrate_netbox_env, netbox_state_status


_GCP_VM_MODULE = "platform/gcp/platform-vm"
_GCP_GLOBAL_CPU_QUOTA = "CPUS_ALL_REGIONS"
_GCP_QUOTA_ACTIVE_STATUSES = {
    "PROVISIONING",
    "REPAIRING",
    "RUNNING",
    "STAGING",
    "STOPPING",
}


def _gcloud_json(args: list[str], *, env: dict[str, str]) -> tuple[Any | None, str]:
    command = ["gcloud", *args, "--format=json"]
    try:
        completed = subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
            env=env,
        )
    except FileNotFoundError:
        return None, "gcloud is unavailable"
    except Exception as exc:
        return None, f"gcloud could not be executed: {exc}"
    if completed.returncode != 0:
        detail = str(completed.stderr or completed.stdout or "").strip()
        return None, detail or f"gcloud exited with status {completed.returncode}"
    try:
        return json.loads(completed.stdout or "null"), ""
    except json.JSONDecodeError:
        return None, "gcloud returned invalid JSON"


def _gcp_resource_name(value: Any) -> str:
    return str(value or "").rstrip("/").rsplit("/", 1)[-1]


def _gcp_vm_name(prefix: str, context_id: str, key: str) -> str:
    prefix_raw = "-".join(token for token in (prefix.strip(), context_id.strip()) if token)
    normalized_prefix = re.sub(r"[^0-9a-z-]", "-", prefix_raw).lower()
    normalized_prefix = re.sub(r"-+", "-", normalized_prefix).strip("-")
    raw = f"{normalized_prefix}-{key}" if normalized_prefix else key
    name = re.sub(r"[^0-9a-z-]", "-", raw).lower()
    name = re.sub(r"-+", "-", name).strip("-")
    if name and not name[0].isalpha():
        name = f"v-{name}"
    return name[:63].rstrip("-")


def _planned_gcp_vms(inputs: dict[str, Any]) -> tuple[list[dict[str, str]], str]:
    vms = inputs.get("vms")
    if not isinstance(vms, dict) or not vms:
        return [], "GCP CPU quota preflight failed: inputs.vms must contain at least one VM"

    default_machine_type = str(inputs.get("machine_type") or "").strip()
    default_zone = str(inputs.get("zone") or "").strip()
    prefix = str(inputs.get("name_prefix") or "")
    context_id = str(inputs.get("context_id") or "")
    planned: list[dict[str, str]] = []
    for key in sorted(vms):
        raw_config = vms.get(key)
        config = raw_config if isinstance(raw_config, dict) else {}
        machine_type = str(config.get("machine_type") or default_machine_type).strip()
        zone = str(config.get("zone") or default_zone).strip()
        name = _gcp_vm_name(prefix, context_id, str(key))
        if not name or not machine_type or not zone:
            return [], (
                "GCP CPU quota preflight failed: each planned VM requires a resolvable "
                "name, machine type, and zone"
            )
        planned.append({"name": name, "machine_type": machine_type, "zone": zone})
    return planned, ""


def _quota_number(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return -1.0


def _format_quota_number(value: float) -> str:
    return str(int(value)) if float(value).is_integer() else f"{value:g}"


def _preflight_gcp_vm_cpu_quota(
    *,
    lifecycle_command: str,
    module_ref: str,
    profile_ref: str,
    runtime: dict[str, Any],
    inputs: dict[str, Any],
    env: dict[str, str],
) -> tuple[str, dict[str, Any]]:
    if str(module_ref or "").strip() != _GCP_VM_MODULE:
        return "", {}
    if not str(profile_ref or "").strip().lower().startswith("gcp"):
        return "", {}
    if str(lifecycle_command or "").strip().lower() not in {"apply", "deploy"}:
        return "", {}

    project_id = _resolve_gcp_project_id(runtime=runtime, inputs=inputs)
    if not project_id:
        return (
            "GCP CPU quota preflight failed: project id could not be resolved from "
            "module inputs or init credentials",
            {},
        )

    planned, planned_error = _planned_gcp_vms(inputs)
    if planned_error:
        return planned_error, {}

    instances_payload, instances_error = _gcloud_json(
        ["compute", "instances", "list", "--project", project_id],
        env=env,
    )
    if instances_error or not isinstance(instances_payload, list):
        return (
            f"GCP CPU quota preflight failed: could not list instances in project "
            f"{project_id}: {instances_error or 'unexpected response'}",
            {},
        )
    instances = {
        (
            _gcp_resource_name(item.get("zone")),
            str(item.get("name") or "").strip(),
        ): item
        for item in instances_payload
        if isinstance(item, dict)
        and _gcp_resource_name(item.get("zone"))
        and str(item.get("name") or "").strip()
    }

    project_payload, project_error = _gcloud_json(
        ["compute", "project-info", "describe", "--project", project_id],
        env=env,
    )
    quotas = project_payload.get("quotas") if isinstance(project_payload, dict) else None
    if project_error or not isinstance(quotas, list):
        return (
            f"GCP CPU quota preflight failed: could not inspect project quota for "
            f"{project_id}: {project_error or 'unexpected response'}",
            {},
        )
    quota = next(
        (
            item
            for item in quotas
            if isinstance(item, dict)
            and str(item.get("metric") or "").strip().upper() == _GCP_GLOBAL_CPU_QUOTA
        ),
        None,
    )
    limit = _quota_number(quota.get("limit") if isinstance(quota, dict) else None)
    usage = _quota_number(quota.get("usage") if isinstance(quota, dict) else None)
    if limit < 0 or usage < 0:
        return (
            f"GCP CPU quota preflight failed: project {project_id} did not return a "
            f"valid {_GCP_GLOBAL_CPU_QUOTA} quota",
            {},
        )

    cpu_cache: dict[tuple[str, str], int] = {}

    def machine_cpus(zone: str, machine_type: str) -> tuple[int, str]:
        key = (zone, machine_type)
        if key in cpu_cache:
            return cpu_cache[key], ""
        payload, detail = _gcloud_json(
            [
                "compute",
                "machine-types",
                "describe",
                machine_type,
                "--project",
                project_id,
                "--zone",
                zone,
            ],
            env=env,
        )
        try:
            cpus = int(payload.get("guestCpus")) if isinstance(payload, dict) else 0
        except (TypeError, ValueError):
            cpus = 0
        if detail or cpus < 1:
            return 0, detail or "machine type response did not contain guestCpus"
        cpu_cache[key] = cpus
        return cpus, ""

    planned_additional = 0
    for vm in planned:
        desired_cpus, shape_error = machine_cpus(vm["zone"], vm["machine_type"])
        if shape_error:
            return (
                f"GCP CPU quota preflight failed: could not resolve {vm['machine_type']} "
                f"in {vm['zone']}: {shape_error}",
                {},
            )
        existing = instances.get((vm["zone"], vm["name"]))
        if not isinstance(existing, dict):
            planned_additional += desired_cpus
            continue
        current_zone = _gcp_resource_name(existing.get("zone")) or vm["zone"]
        current_machine_type = _gcp_resource_name(existing.get("machineType"))
        current_cpus, current_error = machine_cpus(current_zone, current_machine_type)
        if current_error:
            return (
                f"GCP CPU quota preflight failed: could not resolve the current machine "
                f"type for {vm['name']}: {current_error}",
                {},
            )
        planned_additional += max(0, desired_cpus - current_cpus)

    available = max(0.0, limit - usage)
    shortfall = max(0.0, float(planned_additional) - available)
    active_instances: list[dict[str, str]] = []
    for (zone, name), item in sorted(instances.items()):
        status = str(item.get("status") or "").strip().upper()
        if status not in _GCP_QUOTA_ACTIVE_STATUSES:
            continue
        labels = item.get("labels") if isinstance(item.get("labels"), dict) else {}
        active_instances.append(
            {
                "name": name,
                "zone": zone,
                "machine_type": _gcp_resource_name(item.get("machineType")) or "unknown-shape",
                "status": status,
                "role": str(labels.get("role") or "").strip(),
                "workload": str(labels.get("workload") or "").strip(),
            }
        )

    summary = {
        "project_id": project_id,
        "metric": _GCP_GLOBAL_CPU_QUOTA,
        "limit": limit,
        "usage": usage,
        "available": available,
        "planned_additional": planned_additional,
        "shortfall": shortfall,
        "active_instances": active_instances,
    }
    if shortfall <= 0:
        return "", summary

    consumers: list[str] = []
    for item in active_instances:
        ownership = f", role={item['role']}" if item["role"] else ""
        consumers.append(
            f"{item['name']} ({item['machine_type']}, {item['status']}{ownership})"
        )
    consumer_detail = "; ".join(consumers[:5]) or "none visible to the active identity"
    if len(consumers) > 5:
        consumer_detail += f"; and {len(consumers) - 5} more"

    return (
        f"GCP CPU quota preflight failed: project={project_id} "
        f"metric={_GCP_GLOBAL_CPU_QUOTA} limit={_format_quota_number(limit)} "
        f"used={_format_quota_number(usage)} available={_format_quota_number(available)} "
        f"planned_additional={planned_additional} shortfall={_format_quota_number(shortfall)}. "
        f"Active instances: {consumer_detail}. No resources were changed. "
        "Release an existing VM through its owning HybridOps environment, choose a "
        "smaller machine type, or request more global CPU quota, then rerun preflight.",
        summary,
    )


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


def _resolve_gcp_project_id(
    *,
    runtime: dict[str, Any],
    inputs: dict[str, Any],
) -> str:
    direct = str(inputs.get("project_id") or inputs.get("network_project_id") or "").strip()
    if direct:
        return direct

    credentials_dir_raw = str(runtime.get("credentials_dir") or "").strip()
    if not credentials_dir_raw:
        return ""
    tfvars_path = Path(credentials_dir_raw).expanduser().resolve() / "gcp.credentials.tfvars"
    try:
        tfvars = parse_tfvars(tfvars_path)
    except Exception:
        return ""
    return str(tfvars.get("project_id") or "").strip()


def _preflight_gcp_billing(
    *,
    lifecycle_command: str,
    module_ref: str,
    profile_ref: str,
    runtime: dict[str, Any],
    inputs: dict[str, Any],
) -> str:
    if not str(profile_ref or "").strip().lower().startswith("gcp"):
        return ""
    if str(lifecycle_command or "").strip().lower() == "destroy":
        return ""
    if str(module_ref or "").strip() == "org/gcp/project-factory":
        return ""

    project_id = _resolve_gcp_project_id(runtime=runtime, inputs=inputs)
    if not project_id:
        return "GCP billing preflight failed: project id could not be resolved from module inputs or init credentials."

    validated, enabled, detail = diagnose_project_billing(project_id)
    if not validated:
        return (
            f"GCP billing preflight failed: could not validate billing for project {project_id}. "
            + (detail or "Confirm the active gcloud identity can view project billing.")
        )
    if not enabled:
        return (
            f"GCP billing preflight failed: billing is not enabled for project {project_id}. "
            "Enable billing before creating or updating resources. Destroy remains available."
        )
    return ""


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

    billing_error = _preflight_gcp_billing(
        lifecycle_command=str(runtime.get("lifecycle_command") or ""),
        module_ref=module_ref,
        profile_ref=profile_ref,
        runtime=runtime,
        inputs=inputs,
    )
    if billing_error:
        return True, billing_error

    quota_error, quota_summary = _preflight_gcp_vm_cpu_quota(
        lifecycle_command=str(runtime.get("lifecycle_command") or ""),
        module_ref=module_ref,
        profile_ref=profile_ref,
        runtime=runtime,
        inputs=inputs,
        env=env,
    )
    if quota_summary:
        normalized = result.setdefault("normalized_outputs", {})
        preflight_output = normalized.setdefault("preflight", {})
        preflight_output["gcp_cpu_quota"] = quota_summary
    if quota_error:
        return True, quota_error

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
    preflight_output = result.setdefault("normalized_outputs", {}).setdefault("preflight", {})
    preflight_output.update(
        {
            "module_ref": module_ref,
            "profile_ref": profile_ref,
            "pack_id": pack_id,
            "required_credentials": required_credentials,
            "effective_zone_name": str(inputs.get("zone_name") or ""),
        }
    )
    return True, ""
