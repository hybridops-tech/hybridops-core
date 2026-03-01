"""Terragrunt driver stack/profile preparation helpers (internal)."""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

from hyops.runtime.coerce import as_bool
from hyops.runtime.terraform_cloud import apply_runtime_config_env, derive_workspace_name

from .hooks import provider_segment, resolve_export_infra_hook
from .meta import write_runtime_context
from .profile import apply_profile_env, apply_templates
from .workspace import resolve_workspace_policy


def prepare_stack_workspace(
    *,
    pack_stack: Path | None,
    workdir: Path,
    stack_dst: Path,
    runtime_root: Path,
    env: dict[str, str],
    profile: dict[str, Any],
    credential_env: dict[str, str],
    profile_policy: dict[str, Any],
    module_ref: str,
    module_ref_identity: str,
    pack_id: str,
    inputs: dict[str, Any],
    env_name: str,
    run_id: str,
    profile_ref: str,
    state_instance: str,
    execution: dict[str, Any],
    backend_mode: str,
) -> tuple[dict[str, Any] | None, dict[str, Any] | None, str, str, str]:
    """Prepare working stack and resolve workspace/export-hook configs.

    Returns:
      (workspace_policy, export_infra_hook, workspace_name, runtime_inputs_path, error_message)
    """
    if not pack_stack:
        return None, None, "", "", ""

    workspace_name = ""
    runtime_inputs_path = ""

    try:
        workdir.mkdir(parents=True, exist_ok=True)
        (runtime_root / "state" / "terraform").mkdir(parents=True, exist_ok=True)
        if stack_dst.exists():
            shutil.rmtree(stack_dst)
        shutil.copytree(pack_stack, stack_dst)
    except Exception as exc:
        return None, None, "", "", f"workdir setup failed: {exc}"

    try:
        # Populate env from per-env Terraform Cloud config and profile defaults
        # before we derive any workspace/runtime metadata.
        apply_runtime_config_env(env, runtime_root)
        apply_profile_env(env, profile)
        if credential_env:
            env.update(credential_env)

        raw_ws_policy = profile.get("workspace_policy") if isinstance(profile, dict) else None
        ws_provider = ""
        if isinstance(raw_ws_policy, dict) and as_bool(raw_ws_policy.get("enabled"), default=False):
            ws_provider = str(raw_ws_policy.get("provider") or "").strip().lower()
        if not ws_provider:
            ws_provider = provider_segment(module_ref)

        naming_policy = profile_policy.get("naming") if isinstance(profile_policy, dict) else None
        workspace_name, ws_err = derive_workspace_name(
            provider=ws_provider,
            module_ref=module_ref_identity,
            pack_id=pack_id,
            inputs=inputs,
            env=env,
            env_name=env_name,
            naming_policy=naming_policy if isinstance(naming_policy, dict) else None,
        )
        if ws_err and backend_mode == "cloud":
            return None, None, "", "", f"workspace name derivation failed: {ws_err}"

        try:
            write_runtime_context(
                stack_dst,
                module_ref=module_ref,
                state_instance=state_instance,
                run_id=run_id,
                pack_id=pack_id,
                profile_ref=profile_ref,
                inputs=inputs,
                workspace_name=workspace_name,
            )
        except Exception as exc:
            return None, None, "", "", f"failed to write runtime context: {exc}"

        stale_tfvars = stack_dst / "inputs.auto.tfvars.json"
        if stale_tfvars.exists():
            stale_tfvars.unlink()
        runtime_inputs_path = str((stack_dst / "hyops.inputs.json").resolve())
        apply_templates(stack_dst, profile)
    except Exception as exc:
        return None, None, "", "", f"profile preparation failed: {exc}"

    workspace_policy, workspace_error = resolve_workspace_policy(
        profile=profile,
        env=env,
        module_ref=module_ref_identity,
        pack_id=pack_id,
        inputs=inputs,
        naming_policy=profile_policy.get("naming") if isinstance(profile_policy, dict) else None,
    )
    if workspace_error:
        return None, None, "", "", f"workspace policy configuration failed: {workspace_error}"

    export_infra_hook, export_infra_hook_error = resolve_export_infra_hook(
        profile=profile,
        env=env,
        execution=execution,
        module_ref=module_ref,
    )
    if export_infra_hook_error:
        return None, None, "", "", f"export_infra hook configuration failed: {export_infra_hook_error}"

    return workspace_policy, export_infra_hook, workspace_name, runtime_inputs_path, ""
