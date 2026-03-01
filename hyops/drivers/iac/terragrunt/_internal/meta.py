"""Terragrunt driver meta/context helpers (internal)."""

from __future__ import annotations

from pathlib import Path
from typing import Any
import json

from hyops.runtime.evidence import EvidenceWriter
from hyops.runtime.packs import PackResolved


def _write_json_file(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    try:
        path.chmod(0o600)
    except Exception:
        pass


def write_driver_meta(
    ev: EvidenceWriter,
    *,
    command_name: str,
    driver_ref: str,
    profile_ref: str,
    pack_id: str,
    module_ref: str,
    runtime_root: Path,
    workdir: Path,
    stack_dst: Path,
    env: dict[str, str],
    evidence_dir: Path,
    resolved: PackResolved | None,
    pack_error: str,
    profile_path: str,
    profile_error: str,
    profile_policy: dict[str, Any],
    credential_env: dict[str, str],
    required_credentials: list[str],
    available_credentials: list[str],
    credential_error: str,
    credential_contract_error: str,
    workspace_policy: dict[str, Any] | None,
    workspace_error: str,
    export_infra_hook: dict[str, Any] | None,
    export_infra_hook_error: str,
) -> None:
    ev.write_json(
        "driver_meta.json",
        {
            "command": command_name,
            "driver": {"ref": driver_ref, "profile": profile_ref, "pack_id": pack_id},
            "module_ref": module_ref,
            "pack": {
                "packs_root": str(resolved.packs_root) if resolved else "",
                "driver_ref": resolved.driver_ref if resolved else driver_ref,
                "pack_id": resolved.pack_id if resolved else pack_id,
                "stack_dir": str(resolved.stack_dir) if resolved else "",
                "error": pack_error,
            },
            "profile": {
                "path": profile_path,
                "error": profile_error,
                "policy": profile_policy,
            },
            "requirements": {
                "credentials": required_credentials,
                "available_credentials": available_credentials,
                "error": credential_error,
                "contract_error": credential_contract_error,
            },
            "workspace_policy": {
                "enabled": bool(workspace_policy),
                "strict": bool(workspace_policy.get("strict")) if workspace_policy else False,
                "provider": str(workspace_policy.get("provider") or "") if workspace_policy else "",
                "mode": str(workspace_policy.get("mode") or "") if workspace_policy else "",
                "host": str(workspace_policy.get("host") or "") if workspace_policy else "",
                "org": str(workspace_policy.get("org") or "") if workspace_policy else "",
                "credentials_file": str(workspace_policy.get("credentials_file") or "") if workspace_policy else "",
                "workspace_name": str(workspace_policy.get("workspace_name") or "") if workspace_policy else "",
                "error": workspace_error,
            },
            "hooks": {
                "export_infra": {
                    "enabled": bool(export_infra_hook),
                    "strict": bool(export_infra_hook.get("strict")) if export_infra_hook else False,
                    "target": str(export_infra_hook.get("target") or "") if export_infra_hook else "",
                    "command": list(export_infra_hook.get("command") or []) if export_infra_hook else [],
                    "cwd": str(export_infra_hook.get("cwd") or "") if export_infra_hook else "",
                    "hook_root_env": str(export_infra_hook.get("hook_root_env") or "") if export_infra_hook else "",
                    "hook_root": str(export_infra_hook.get("hook_root") or "") if export_infra_hook else "",
                    "push_to_netbox": bool(export_infra_hook.get("push_to_netbox")) if export_infra_hook else False,
                    "netbox_dataset_json": str(export_infra_hook.get("netbox_dataset_json") or "") if export_infra_hook else "",
                    "netbox_dataset_csv": str(export_infra_hook.get("netbox_dataset_csv") or "") if export_infra_hook else "",
                    "netbox_sync_command": list(export_infra_hook.get("netbox_sync_command") or []) if export_infra_hook else [],
                    "netbox_sync_cwd": str(export_infra_hook.get("netbox_sync_cwd") or "") if export_infra_hook else "",
                    "error": export_infra_hook_error,
                }
            },
            "paths": {
                "runtime_root": str(runtime_root),
                "workdir": str(workdir),
                "stack": str(stack_dst),
                "evidence_dir": str(evidence_dir),
            },
            "env": {
                "HYOPS_RUNTIME_ROOT": env.get("HYOPS_RUNTIME_ROOT", ""),
                "HYOPS_PACKS_ROOT": env.get("HYOPS_PACKS_ROOT", ""),
                "HYOPS_TERRAFORM_BACKEND_MODE": env.get("HYOPS_TERRAFORM_BACKEND_MODE", ""),
                **credential_env,
            },
        },
    )


def write_runtime_context(
    stack_dir: Path,
    *,
    module_ref: str,
    state_instance: str,
    run_id: str,
    pack_id: str,
    profile_ref: str,
    inputs: dict[str, Any],
    workspace_name: str,
) -> None:
    module_id = module_ref.replace("/", "__") if module_ref else "unknown_module"
    normalized_instance = str(state_instance or "").strip()
    if normalized_instance:
        module_id = f"{module_id}__{normalized_instance.replace('#', '__')}"

    _write_json_file(
        stack_dir / "hyops.meta.json",
        {
            "driver": "iac/terragrunt",
            "module_ref": module_ref,
            "state_instance": normalized_instance,
            "module_id": module_id,
            "pack_id": pack_id,
            "profile_ref": profile_ref,
            "run_id": run_id,
            "workspace_name": str(workspace_name or "").strip(),
        },
    )

    _write_json_file(stack_dir / "hyops.inputs.json", inputs)


def write_runtime_inputs(stack_dir: Path, inputs: dict[str, Any]) -> Path:
    p = stack_dir / "hyops.inputs.json"
    _write_json_file(p, inputs)
    return p
