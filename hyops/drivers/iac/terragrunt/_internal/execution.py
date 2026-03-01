"""Terragrunt driver execution/preflight helpers."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from hyops.runtime.coerce import as_argv
from .proc import run_capture_with_policy


def resolve_terragrunt_config(profile: dict[str, Any]) -> dict[str, Any]:
    """Resolve terragrunt command config from profile."""
    terragrunt_cfg = profile.get("terragrunt") if isinstance(profile, dict) else {}
    if not isinstance(terragrunt_cfg, dict):
        terragrunt_cfg = {}

    return {
        "tg_bin": str(terragrunt_cfg.get("bin") or "terragrunt").strip() or "terragrunt",
        "init_args": as_argv(terragrunt_cfg.get("init_args"), ["init", "-no-color"]),
        "apply_args": as_argv(terragrunt_cfg.get("apply_args"), ["apply", "-auto-approve", "-no-color"]),
        "destroy_args": as_argv(terragrunt_cfg.get("destroy_args"), ["destroy", "-auto-approve", "-no-color"]),
        "import_args": as_argv(terragrunt_cfg.get("import_args"), ["import", "-no-color"]),
        "force_unlock_args": as_argv(terragrunt_cfg.get("force_unlock_args"), ["force-unlock"]),
        "plan_args": as_argv(terragrunt_cfg.get("plan_args"), ["plan", "-input=false", "-no-color"]),
        "validate_args": as_argv(terragrunt_cfg.get("validate_args"), ["validate", "-no-color"]),
        "output_args": as_argv(terragrunt_cfg.get("output_args"), ["output", "-json", "-no-color"]),
    }


def run_terragrunt_init(
    *,
    tg_bin: str,
    init_args: list[str],
    stack_dst: Path,
    env: dict[str, str],
    evidence_dir: Path,
    policy_timeout_s: int | None,
    policy_redact: bool,
    policy_retries: int,
    tg_log: Path,
) -> str:
    """Run `terragrunt init`; return empty string on success else error message."""
    r_init = run_capture_with_policy(
        argv=[tg_bin, *init_args],
        cwd=str(stack_dst),
        env=env,
        evidence_dir=evidence_dir,
        label="terragrunt_init",
        timeout_s=policy_timeout_s,
        redact=policy_redact,
        retries=policy_retries,
        tee_path=tg_log,
        stream=False,
    )
    if r_init.rc == 0:
        return ""

    stderr = str(r_init.stderr or "")
    stdout = str(r_init.stdout or "")
    combined = (stderr + "\n" + stdout).lower()
    if ("no space" in combined) and ("left on device" in combined):
        tmpdir = str(env.get("TMPDIR") or "").strip() or "/tmp"
        return f"terragrunt init failed: no space left on device (TMPDIR={tmpdir})"
    return "terragrunt init failed"


def run_terragrunt_operation(
    *,
    command_name: str,
    request: dict[str, Any],
    tg_bin: str,
    apply_args: list[str],
    destroy_args: list[str],
    import_args: list[str],
    force_unlock_args: list[str],
    plan_args: list[str],
    validate_args: list[str],
    output_args: list[str],
    stack_dst: Path,
    env: dict[str, str],
    evidence_dir: Path,
    policy_timeout_s: int | None,
    policy_redact: bool,
    policy_retries: int,
    tg_log: Path,
) -> tuple[dict[str, Any], str]:
    """Run terragrunt lifecycle op and optionally collect outputs.

    Returns: (outputs, error_message). `outputs` is non-empty for apply/import
    when `terragrunt output -json` succeeds.
    """
    exec_args, exec_label, exec_error, exec_config_error = resolve_exec_operation(
        command_name=command_name,
        request=request if isinstance(request, dict) else {},
        apply_args=apply_args,
        destroy_args=destroy_args,
        import_args=import_args,
        force_unlock_args=force_unlock_args,
        plan_args=plan_args,
        validate_args=validate_args,
    )
    if exec_config_error:
        return {}, exec_config_error

    r_exec = run_capture_with_policy(
        argv=[tg_bin, *exec_args],
        cwd=str(stack_dst),
        env=env,
        evidence_dir=evidence_dir,
        label=exec_label,
        timeout_s=policy_timeout_s,
        redact=policy_redact,
        retries=policy_retries,
        tee_path=tg_log,
        stream=True,
    )
    if r_exec.rc != 0:
        return {}, exec_error

    outputs: dict[str, Any] = {}
    if command_name in ("apply", "import"):
        r_out = run_capture_with_policy(
            argv=[tg_bin, *output_args],
            cwd=str(stack_dst),
            env=env,
            evidence_dir=evidence_dir,
            label="terragrunt_output",
            timeout_s=policy_timeout_s,
            redact=policy_redact,
            retries=policy_retries,
            tee_path=tg_log,
            stream=False,
        )
        if r_out.rc == 0:
            outputs = parse_terragrunt_outputs(r_out.stdout or "")
    return outputs, ""


def resolve_exec_operation(
    *,
    command_name: str,
    request: dict[str, Any],
    apply_args: list[str],
    destroy_args: list[str],
    import_args: list[str],
    force_unlock_args: list[str],
    plan_args: list[str],
    validate_args: list[str],
) -> tuple[list[str], str, str, str]:
    """Resolve terragrunt operation args + labels.

    Returns: (exec_args, exec_label, exec_error, error_message)
    """
    exec_args = list(apply_args)
    exec_label = "terragrunt_apply"
    exec_error = "terragrunt apply failed"

    if command_name == "plan":
        return list(plan_args), "terragrunt_plan", "terragrunt plan failed", ""
    if command_name == "validate":
        return list(validate_args), "terragrunt_validate", "terragrunt validate failed", ""
    if command_name == "destroy":
        return list(destroy_args), "terragrunt_destroy", "terragrunt destroy failed", ""
    if command_name == "import":
        import_payload = request.get("import")
        if not isinstance(import_payload, dict):
            return [], "", "", "import requires request.import payload"
        resource_address = str(import_payload.get("resource_address") or "").strip()
        resource_id = str(import_payload.get("resource_id") or "").strip()
        if not resource_address or not resource_id:
            return [], "", "", "import requires non-empty resource_address and resource_id"
        return [*import_args, resource_address, resource_id], "terragrunt_import", "terragrunt import failed", ""
    if command_name == "state_unlock":
        state_payload = request.get("state")
        if not isinstance(state_payload, dict):
            return [], "", "", "state_unlock requires request.state payload"
        lock_id = str(state_payload.get("lock_id") or "").strip()
        force_unlock = bool(state_payload.get("force"))
        if not force_unlock:
            return [], "", "", "state_unlock requires force=true"
        if not lock_id:
            return [], "", "", "state_unlock requires non-empty lock_id"
        unlock_args = list(force_unlock_args)
        if "-force" not in unlock_args and "--force" not in unlock_args:
            unlock_args.append("-force")
        return [*unlock_args, lock_id], "terragrunt_force_unlock", "terragrunt force-unlock failed", ""

    return exec_args, exec_label, exec_error, ""


def parse_terragrunt_outputs(raw_stdout: str) -> dict[str, Any]:
    """Parse `terragrunt output -json` payload into flattened outputs."""
    outputs: dict[str, Any] = {}
    try:
        raw = json.loads((raw_stdout or "").strip() or "{}")
        if isinstance(raw, dict):
            for k, v in raw.items():
                if isinstance(v, dict) and "value" in v:
                    outputs[k] = v.get("value")
                else:
                    outputs[k] = v
    except Exception:
        outputs = {}
    return outputs
