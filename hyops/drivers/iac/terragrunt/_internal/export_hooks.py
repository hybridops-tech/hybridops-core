"""Terragrunt driver post-apply export/netbox hooks (internal)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
import shutil
import sys

from hyops.runtime.coerce import as_argv
from hyops.runtime.evidence import EvidenceWriter
from hyops.runtime.module_state import read_module_state

from .hooks import dataset_has_rows
from .netbox import hydrate_netbox_env, netbox_state_status
from .proc import run_capture_with_policy


def _resolve_current_hyops_bin() -> str:
    argv0 = str(sys.argv[0] or "").strip()
    if argv0:
        if "/" in argv0 or "\\" in argv0:
            resolved = Path(argv0).expanduser().resolve()
            parts = tuple(resolved.parts)
            if len(parts) >= 2 and parts[-2:] == ("hyops", "cli.py"):
                return str(Path(sys.executable).expanduser().resolve())
            return str(resolved)
        resolved = shutil.which(argv0)
        if resolved:
            return str(Path(resolved).expanduser().resolve())
    resolved = shutil.which("hyops")
    if resolved:
        return str(Path(resolved).expanduser().resolve())
    return str(Path(sys.executable).expanduser().resolve())


def _rewrite_hyops_hook_command(argv: list[str]) -> list[str]:
    if not argv:
        return []
    head = str(argv[0] or "").strip()
    if head != "hyops":
        return list(argv)
    resolved = _resolve_current_hyops_bin()
    resolved_path = Path(resolved)
    if resolved_path.name.startswith("python"):
        return [resolved, "-m", "hyops.cli", *list(argv[1:])]
    rewritten = list(argv)
    rewritten[0] = resolved
    return rewritten


def _replace_dataset_arg(argv: list[str], dataset_path: str) -> list[str]:
    out = list(argv)
    for idx, token in enumerate(out[:-1]):
        if str(token) == "--dataset":
            out[idx + 1] = dataset_path
            return out
    out.extend(["--dataset", dataset_path])
    return out


def _infer_cluster_from_vm_tags(*, tags: list[str]) -> str:
    lowered = {str(t or "").strip().lower() for t in tags if str(t or "").strip()}
    for env in ("dev", "staging", "prod", "production"):
        if env in lowered:
            env_key = "prod" if env == "production" else env
            return f"onprem-{env_key}"
    return "onprem-core"


def _build_destroy_vm_dataset_from_state(
    *,
    runtime_root: Path,
    module_ref: str,
    state_instance: str,
    evidence_dir: Path,
) -> tuple[Path | None, str]:
    if module_ref != "platform/onprem/platform-vm":
        return None, ""
    state_dir = (runtime_root / "state").resolve()
    try:
        payload = read_module_state(state_dir, module_ref, state_instance=state_instance or None)
    except Exception as exc:
        return None, f"destroy sync could not read prior module state: {exc}"

    if str(payload.get("status") or "").strip().lower() != "ok":
        return None, ""
    outputs = payload.get("outputs")
    if not isinstance(outputs, dict):
        return None, ""
    raw_vms = outputs.get("vms")
    if not isinstance(raw_vms, dict) or not raw_vms:
        return None, ""

    rows: list[dict[str, Any]] = []
    for vm in raw_vms.values():
        if not isinstance(vm, dict):
            continue
        vm_name = str(vm.get("vm_name") or "").strip()
        if not vm_name:
            continue
        tags = vm.get("tags")
        tags_list = [str(t).strip() for t in tags] if isinstance(tags, list) else []
        rows.append(
            {
                "name": vm_name,
                "cluster": _infer_cluster_from_vm_tags(tags=tags_list),
                "tags": ";".join([t for t in tags_list if t]),
            }
        )
    if not rows:
        return None, ""

    path = (evidence_dir / "hook_netbox_destroy_vms.dataset.json").resolve()
    path.write_text(json.dumps(rows, indent=2), encoding="utf-8")
    return path, ""


def run_apply_export_hooks(
    *,
    ev: EvidenceWriter,
    command_name: str,
    export_infra_hook: dict[str, Any] | None,
    stack_dst: Path,
    env: dict[str, str],
    evidence_dir: Path,
    policy_timeout_s: int | None,
    policy_redact: bool,
    policy_retries: int,
    tg_log: Path,
    contract: Any,
    module_ref: str,
    state_instance: str,
    runtime: dict[str, Any],
    runtime_root: Path,
    env_name: str,
    result: dict[str, Any],
) -> str:
    """Run export_infra/netbox sync hooks after apply.

    Returns an error string for strict failures; otherwise empty.
    """
    if command_name not in ("apply", "destroy") or not export_infra_hook:
        return ""

    strict_netbox = bool(export_infra_hook.get("strict"))
    push_to_netbox_requested = bool(export_infra_hook.get("push_to_netbox"))
    push_to_netbox_effective = push_to_netbox_requested

    hook_cwd = str(stack_dst)
    hook_cwd_override = str(export_infra_hook.get("cwd") or "").strip()
    if hook_cwd_override:
        hook_cwd = hook_cwd_override

    hook_timeout = export_infra_hook.get("timeout_s")
    hook_timeout_s = int(hook_timeout) if isinstance(hook_timeout, int) and hook_timeout > 0 else policy_timeout_s
    hook_redact = bool(export_infra_hook.get("redact", policy_redact))

    if command_name == "apply":
        hook_command = export_infra_hook.get("command")
        if not isinstance(hook_command, list) or not hook_command:
            return "export_infra hook command is empty"
        hook_command = _rewrite_hyops_hook_command(list(hook_command))

        r_hook = run_capture_with_policy(
            argv=hook_command,
            cwd=hook_cwd,
            env=env,
            evidence_dir=evidence_dir,
            label="hook_export_infra",
            timeout_s=hook_timeout_s,
            redact=hook_redact,
            retries=policy_retries,
            tee_path=tg_log,
            stream=True,
        )

        ev.write_json(
            "hook_export_infra.json",
            {
                "command": hook_command,
                "cwd": hook_cwd,
                "target": str(export_infra_hook.get("target") or ""),
                "strict": bool(strict_netbox),
                "push_to_netbox": bool(push_to_netbox_requested),
                "netbox_dataset_json": str(export_infra_hook.get("netbox_dataset_json") or ""),
                "netbox_dataset_csv": str(export_infra_hook.get("netbox_dataset_csv") or ""),
                "rc": int(r_hook.rc),
            },
        )

        if r_hook.rc != 0:
            hook_msg = f"export_infra hook failed with rc={r_hook.rc}"
            if strict_netbox:
                return hook_msg
            result["warnings"].append(hook_msg)
            # If export failed, don't attempt downstream NetBox sync in non-strict mode.
            push_to_netbox_effective = False

    if push_to_netbox_effective:
        contract_error = contract.validate_push_to_netbox(
            command_name=command_name,
            module_ref=module_ref,
            runtime=runtime if isinstance(runtime, dict) else {},
        )
        if contract_error:
            if strict_netbox:
                return contract_error
            result["warnings"].append(f"push_to_netbox disabled (non-strict): {contract_error}")
            push_to_netbox_effective = False

    dataset_json = Path(str(export_infra_hook.get("netbox_dataset_json") or "")).expanduser().resolve()
    dataset_csv = Path(str(export_infra_hook.get("netbox_dataset_csv") or "")).expanduser().resolve()
    destroy_dataset_json: Path | None = None
    if command_name == "destroy" and push_to_netbox_effective:
        destroy_dataset_json, destroy_dataset_err = _build_destroy_vm_dataset_from_state(
            runtime_root=runtime_root,
            module_ref=module_ref,
            state_instance=state_instance,
            evidence_dir=evidence_dir,
        )
        if destroy_dataset_err:
            if strict_netbox:
                return destroy_dataset_err
            result["warnings"].append(f"push_to_netbox disabled (non-strict): {destroy_dataset_err}")
            push_to_netbox_effective = False
        elif destroy_dataset_json is None:
            push_to_netbox_effective = False

    if push_to_netbox_effective:
        hydrate_warnings, missing = hydrate_netbox_env(env, runtime_root)
        if hydrate_warnings:
            result["warnings"].extend(hydrate_warnings)

        if missing:
            missing_str = ", ".join(missing)
            nb_state = netbox_state_status(runtime_root)
            hint = f"push_to_netbox requires {missing_str}. "
            if "NETBOX_API_TOKEN" in missing:
                vault_file = (runtime_root / "vault" / "bootstrap.vault.env").resolve()
                env_hint = env_name or "<env>"
                hint += f"Generate/store NETBOX_API_TOKEN in runtime vault via: hyops secrets ensure --env {env_hint} NETBOX_API_TOKEN. "
                hint += f"(vault: {vault_file}) "
            if "NETBOX_API_URL" in missing and nb_state and nb_state not in ("ok", "ready"):
                hint += f"NetBox module state platform/onprem/netbox is not ready (status={nb_state}); apply it to publish netbox_api_url. "
            if strict_netbox:
                return hint.strip()
            result["warnings"].append(
                f"push_to_netbox disabled (non-strict): {hint.strip()}"
            )
            push_to_netbox_effective = False

    if push_to_netbox_effective and command_name == "apply":
        has_rows, dataset_err = dataset_has_rows(json_path=dataset_json, csv_path=dataset_csv)
        if not has_rows:
            if strict_netbox:
                return f"push_to_netbox dataset check failed: {dataset_err}"
            result["warnings"].append(f"push_to_netbox disabled (non-strict): dataset check failed: {dataset_err}")
            push_to_netbox_effective = False

    if push_to_netbox_effective:
        sync_command = as_argv(export_infra_hook.get("netbox_sync_command"), default=[])
        if not sync_command:
            if strict_netbox:
                return "push_to_netbox requires non-empty netbox_sync_command"
            result["warnings"].append("push_to_netbox disabled (non-strict): netbox_sync_command not configured")
            push_to_netbox_effective = False
        else:
            sync_command = _rewrite_hyops_hook_command(list(sync_command))
            if command_name == "destroy":
                sync_command = _replace_dataset_arg(sync_command, str(destroy_dataset_json))
                sync_command.append("--destroy-sync")
                if str(env.get("HYOPS_NETBOX_SYNC_DESTROY_HARD_DELETE") or "").strip().lower() in (
                    "1",
                    "true",
                    "yes",
                    "on",
                ):
                    sync_command.append("--hard-delete")

    if push_to_netbox_effective:
        sync_cwd = str(export_infra_hook.get("netbox_sync_cwd") or "").strip() or str(stack_dst)
        sync_timeout = export_infra_hook.get("netbox_sync_timeout_s")
        sync_timeout_s = int(sync_timeout) if isinstance(sync_timeout, int) and sync_timeout > 0 else policy_timeout_s

        r_sync = run_capture_with_policy(
            argv=sync_command,
            cwd=sync_cwd,
            env=env,
            evidence_dir=evidence_dir,
            label="hook_netbox_sync",
            timeout_s=sync_timeout_s,
            redact=policy_redact,
            retries=policy_retries,
            tee_path=tg_log,
            stream=True,
        )

        ev.write_json(
            "hook_netbox_sync.json",
            {
                "command": sync_command,
                "cwd": sync_cwd,
                "dataset_json": str(destroy_dataset_json or dataset_json),
                "dataset_csv": str(dataset_csv),
                "rc": int(r_sync.rc),
            },
        )

        if r_sync.rc != 0:
            if strict_netbox:
                return f"netbox sync failed with rc={r_sync.rc}"
            result["warnings"].append(f"netbox sync failed (non-strict) with rc={r_sync.rc}")

    return ""
