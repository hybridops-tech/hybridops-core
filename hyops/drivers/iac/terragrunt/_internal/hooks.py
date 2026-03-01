"""Terragrunt driver hooks helpers (internal)."""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any

from hyops.runtime.coerce import as_bool


def provider_segment(module_ref: str) -> str:
    parts = [p for p in (module_ref or "").strip().split("/") if p]
    if len(parts) < 2:
        return ""
    return parts[1].strip().lower()


def default_export_target(module_ref: str) -> str:
    provider = provider_segment(module_ref)
    if not provider:
        return ""

    if provider in ("azure", "gcp", "aws", "hetzner"):
        return f"cloud-{provider}"

    if provider in ("proxmox", "vmware"):
        return f"onprem-{provider}"

    if provider == "onprem":
        parts = [p for p in (module_ref or "").strip().split("/") if p]
        for token in parts[2:]:
            t = token.strip().lower()
            if t in ("proxmox", "vmware"):
                return f"onprem-{t}"
        return "onprem-proxmox"

    return provider


def default_netbox_dataset_kind(module_ref: str) -> str:
    """Infer which NetBox dataset should be produced/consumed for a module.

    Default is VM inventory exports, but some modules (like SDN) export IPAM assets.
    """
    ref = (module_ref or "").strip().lower()
    if not ref:
        return "vms"
    if ref.endswith("/network-sdn") or "network-sdn" in ref:
        return "ipam_prefixes"
    return "vms"


def render_hook_token(value: str, tokens: dict[str, str]) -> str:
    out = str(value)
    for key, token in tokens.items():
        out = out.replace("{" + key + "}", token)
    return out


def path_from_runtime_env(
    *,
    env: dict[str, str],
    env_key: str,
    default_rel: str,
) -> Path:
    runtime_root_raw = str(env.get("HYOPS_RUNTIME_ROOT") or "").strip()
    runtime_root = Path(runtime_root_raw or ".").expanduser().resolve()

    raw = str(env.get(env_key) or "").strip()
    if not raw:
        return (runtime_root / default_rel).resolve()

    p = Path(raw).expanduser()
    return p if p.is_absolute() else (runtime_root / p).resolve()


def resolve_export_infra_hook(
    *,
    profile: dict[str, Any],
    env: dict[str, str],
    execution: dict[str, Any],
    module_ref: str,
) -> tuple[dict[str, Any] | None, str]:
    raw_exec_hooks = execution.get("hooks")
    if raw_exec_hooks is None:
        return None, ""

    if not isinstance(raw_exec_hooks, dict):
        return None, "execution.hooks must be a mapping"

    raw_export = raw_exec_hooks.get("export_infra")
    if raw_export is None:
        return None, ""

    if isinstance(raw_export, bool):
        export_cfg = {"enabled": bool(raw_export), "push_to_netbox": False}
    elif isinstance(raw_export, dict):
        export_cfg = raw_export
    else:
        return None, "execution.hooks.export_infra must be a bool or mapping"

    if not as_bool(export_cfg.get("enabled"), default=False):
        return None, ""

    profile_hooks = profile.get("hooks") or {}
    if not isinstance(profile_hooks, dict):
        return None, "profile.hooks must be a mapping"

    profile_export = profile_hooks.get("export_infra")
    if not isinstance(profile_export, dict):
        return None, "profile.hooks.export_infra must be a mapping when execution hook is enabled"

    raw_command = profile_export.get("command")
    if not isinstance(raw_command, list) or not raw_command:
        return None, "profile.hooks.export_infra.command must be a non-empty list"

    target = str(
        export_cfg.get("target")
        or profile_export.get("target_default")
        or default_export_target(module_ref)
    ).strip().lower()
    if not target:
        return None, "execution.hooks.export_infra.target is required"

    push_to_netbox = as_bool(export_cfg.get("push_to_netbox"), default=False)

    dataset_kind = str(export_cfg.get("dataset_kind") or export_cfg.get("dataset") or "").strip().lower()
    if not dataset_kind:
        dataset_kind = default_netbox_dataset_kind(module_ref)

    hook_root_env = str(profile_export.get("hook_root_env") or "HYOPS_EXPORT_HOOK_ROOT").strip()
    hook_root_default = str(profile_export.get("hook_root_default") or "").strip()
    hook_root = str(env.get(hook_root_env) or hook_root_default).strip()

    if dataset_kind in ("ipam_prefixes", "ipam-prefixes", "ipam", "network"):
        netbox_dataset_json = path_from_runtime_env(
            env=env,
            env_key="NETBOX_IPAM_PREFIXES_AUTO_JSON",
            default_rel="state/netbox/network/ipam-prefixes.auto.json",
        )
        netbox_dataset_csv = path_from_runtime_env(
            env=env,
            env_key="NETBOX_IPAM_PREFIXES_AUTO_CSV",
            default_rel="state/netbox/network/ipam-prefixes.auto.csv",
        )
    else:
        netbox_dataset_json = path_from_runtime_env(
            env=env,
            env_key="NETBOX_VMS_AUTO_JSON",
            default_rel="state/netbox/vms/vms.auto.json",
        )
        netbox_dataset_csv = path_from_runtime_env(
            env=env,
            env_key="NETBOX_VMS_AUTO_CSV",
            default_rel="state/netbox/vms/vms.auto.csv",
        )

    provider = provider_segment(module_ref)
    tokens = {
        "target": target,
        "module_ref": module_ref,
        "provider": provider,
        "dataset_kind": dataset_kind,
        "hook_root": hook_root,
        "runtime_root": str(path_from_runtime_env(env=env, env_key="HYOPS_RUNTIME_ROOT", default_rel=".")),
        "netbox_dataset_json": str(netbox_dataset_json),
        "netbox_dataset_csv": str(netbox_dataset_csv),
    }

    command: list[str] = []
    for item in raw_command:
        rendered = render_hook_token(str(item), tokens).strip()
        if not rendered:
            return None, "profile.hooks.export_infra.command contains empty argv item"
        if "{hook_root}" in rendered:
            return None, f"missing hook root; set env {hook_root_env}"
        command.append(rendered)

    cwd = ""
    raw_cwd = str(profile_export.get("cwd") or "").strip()
    if raw_cwd:
        rendered_cwd = render_hook_token(raw_cwd, tokens).strip()
        if "{hook_root}" in rendered_cwd:
            return None, f"missing hook root; set env {hook_root_env}"
        if rendered_cwd:
            cwd = str(Path(rendered_cwd).expanduser().resolve())

    timeout_s: int | None = None
    raw_timeout = profile_export.get("timeout_s")
    if raw_timeout is not None:
        try:
            parsed = int(raw_timeout)
        except Exception:
            return None, "profile.hooks.export_infra.timeout_s must be an integer"
        if parsed > 0:
            timeout_s = parsed

    netbox_sync_command: list[str] = []
    raw_sync_command = profile_export.get("netbox_sync_command")
    if raw_sync_command is not None:
        if not isinstance(raw_sync_command, list) or not raw_sync_command:
            return None, "profile.hooks.export_infra.netbox_sync_command must be a non-empty list when set"
        for item in raw_sync_command:
            rendered = render_hook_token(str(item), tokens).strip()
            if not rendered:
                return None, "profile.hooks.export_infra.netbox_sync_command contains empty argv item"
            netbox_sync_command.append(rendered)

    if push_to_netbox and not netbox_sync_command:
        return None, "push_to_netbox=true requires profile.hooks.export_infra.netbox_sync_command"

    netbox_sync_cwd = ""
    raw_sync_cwd = str(profile_export.get("netbox_sync_cwd") or "").strip()
    if raw_sync_cwd:
        rendered_sync_cwd = render_hook_token(raw_sync_cwd, tokens).strip()
        if rendered_sync_cwd:
            netbox_sync_cwd = str(Path(rendered_sync_cwd).expanduser().resolve())

    netbox_sync_timeout_s: int | None = None
    raw_sync_timeout = profile_export.get("netbox_sync_timeout_s")
    if raw_sync_timeout is not None:
        try:
            parsed_sync_timeout = int(raw_sync_timeout)
        except Exception:
            return None, "profile.hooks.export_infra.netbox_sync_timeout_s must be an integer"
        if parsed_sync_timeout > 0:
            netbox_sync_timeout_s = parsed_sync_timeout

    return (
        {
            "enabled": True,
            "target": target,
            "dataset_kind": dataset_kind,
            "command": command,
            "cwd": cwd,
            "strict": as_bool(export_cfg.get("strict"), default=as_bool(profile_export.get("strict"), default=False)),
            "redact": as_bool(profile_export.get("redact"), default=True),
            "timeout_s": timeout_s,
            "hook_root_env": hook_root_env,
            "hook_root": hook_root,
            "push_to_netbox": push_to_netbox,
            "netbox_dataset_json": str(netbox_dataset_json),
            "netbox_dataset_csv": str(netbox_dataset_csv),
            "netbox_sync_command": netbox_sync_command,
            "netbox_sync_cwd": netbox_sync_cwd,
            "netbox_sync_timeout_s": netbox_sync_timeout_s,
        },
        "",
    )


def dataset_has_rows(*, json_path: Path, csv_path: Path) -> tuple[bool, str]:
    if json_path.exists():
        try:
            payload = json.loads(json_path.read_text(encoding="utf-8"))
        except Exception as e:
            return False, f"invalid JSON dataset at {json_path}: {e}"

        if isinstance(payload, list) and len(payload) > 0:
            return True, ""

        return False, f"empty JSON dataset at {json_path}"

    if csv_path.exists():
        try:
            with csv_path.open("r", encoding="utf-8", newline="") as f:
                reader = csv.DictReader(f)
                for _ in reader:
                    return True, ""
        except Exception as e:
            return False, f"invalid CSV dataset at {csv_path}: {e}"

        return False, f"empty CSV dataset at {csv_path}"

    return False, f"dataset not found (checked {json_path} and {csv_path})"
