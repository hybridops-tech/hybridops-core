"""Terraform Cloud commands.

purpose: Expose Terraform Cloud helper operations through hyops CLI.
maintainer: HybridOps.Tech
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from hyops.drivers.iac.terraform_cloud.tools.configure_workspace_execution_mode import (
    main as configure_workspace_mode_main,
)
from hyops.drivers.iac.terraform_cloud.workspace import (
    default_workspace_description,
    delete_workspace,
    ensure_workspace,
)
from hyops.runtime.exitcodes import INTERNAL_ERROR
from hyops.runtime.paths import resolve_runtime_paths
from hyops.runtime.terraform_cloud import derive_workspace_name
from hyops.runtime.terraform_cloud import (
    DEFAULT_TFC_CREDENTIALS_FILE,
    DEFAULT_TFC_HOST,
    resolve_config as resolve_tfc_config,
    runtime_config_path,
)


def _exit_code_from_system_exit(exc: SystemExit) -> int:
    code = exc.code
    if code is None:
        return 0
    if isinstance(code, bool):
        return int(code)
    if isinstance(code, int):
        return code
    if isinstance(code, str):
        try:
            return int(code)
        except ValueError:
            return INTERNAL_ERROR
    return INTERNAL_ERROR


def add_tfc_subparser(sp: argparse._SubParsersAction) -> None:
    p = sp.add_parser("tfc", help="Terraform Cloud helper commands.")
    ssp = p.add_subparsers(dest="tfc_cmd", required=True)

    q = ssp.add_parser(
        "workspace-mode",
        help="Ensure Terraform Cloud workspace execution mode.",
    )
    q.add_argument("workspace_name", help="Terraform Cloud workspace name.")
    q.add_argument("org", nargs="?", default="", help="Terraform Cloud organization.")
    q.add_argument(
        "execution_mode",
        nargs="?",
        default="local",
        choices=("local", "remote", "agent"),
        help="Execution mode.",
    )
    q.add_argument("--host", default="", help="Terraform Cloud host.")
    q.add_argument(
        "--credentials-file",
        default="",
        help="Terraform credentials file path.",
    )
    q.add_argument("--root", default="", help="Runtime root for Terraform Cloud config discovery.")
    q.add_argument("--env-name", "--env", dest="env_name", default="", help="Runtime env for Terraform Cloud config discovery.")
    q.add_argument("--description", default="", help="Optional workspace description override.")
    q.add_argument("--strict", action="store_true", help="Return non-zero on policy/tooling errors.")
    q.add_argument("--json", action="store_true", help="Emit result as JSON.")
    q.set_defaults(_handler=run_workspace_mode)

    e = ssp.add_parser(
        "workspace-ensure",
        help="Ensure Terraform Cloud workspace exists (create if missing) and set execution mode.",
    )
    e.add_argument(
        "workspace_name",
        nargs="?",
        default="",
        help="Terraform Cloud workspace name (optional if deriving via --provider/--module-ref/--pack-id).",
    )
    e.add_argument("--org", default="", help="Terraform Cloud organization.")
    e.add_argument(
        "--execution-mode",
        dest="execution_mode",
        default="local",
        choices=("local", "remote", "agent"),
        help="Execution mode.",
    )
    e.add_argument("--host", default="", help="Terraform Cloud host.")
    e.add_argument(
        "--credentials-file",
        default="",
        help="Terraform credentials file path.",
    )
    e.add_argument("--description", default="", help="Optional workspace description override.")
    e.add_argument("--strict", action="store_true", help="Return non-zero on API/tooling errors.")
    e.add_argument("--json", action="store_true", help="Emit result as JSON.")
    e.add_argument("--provider", default="", help="Provider token for derived naming (e.g. gcp, azure, proxmox).")
    e.add_argument("--module-ref", default="", help="Module ref for derived naming (e.g. org/gcp/project-factory).")
    e.add_argument("--pack-id", default="", help="Pack id for derived naming.")
    e.add_argument("--env-name", "--env", dest="env_name", default="", help="Environment namespace for derived naming (e.g. dev, shared).")
    e.add_argument("--workspace-prefix", default="", help="Workspace prefix for derived naming.")
    e.add_argument("--name-prefix", default="", help="Override name_prefix token for derived naming.")
    e.add_argument("--context-id", default="", help="Override context_id token for derived naming.")
    e.add_argument("--root", default="", help="Runtime root for Terraform Cloud config discovery.")
    e.set_defaults(_handler=run_workspace_ensure)

    d = ssp.add_parser(
        "workspace-delete",
        help="Delete a Terraform Cloud workspace by name (safe delete by default).",
    )
    d.add_argument(
        "workspace_name",
        nargs="?",
        default="",
        help="Terraform Cloud workspace name (optional if deriving via --provider/--module-ref/--pack-id).",
    )
    d.add_argument("--org", default="", help="Terraform Cloud organization.")
    d.add_argument("--host", default="", help="Terraform Cloud host.")
    d.add_argument(
        "--credentials-file",
        default="",
        help="Terraform credentials file path.",
    )
    d.add_argument("--force", action="store_true", help="Delete the workspace even when Terraform Cloud cannot safe-delete it.")
    d.add_argument("--strict", action="store_true", help="Return non-zero on API/tooling errors.")
    d.add_argument("--json", action="store_true", help="Emit result as JSON.")
    d.add_argument("--provider", default="", help="Provider token for derived naming (e.g. gcp, azure, proxmox).")
    d.add_argument("--module-ref", default="", help="Module ref for derived naming (e.g. org/gcp/project-factory).")
    d.add_argument("--pack-id", default="", help="Pack id for derived naming.")
    d.add_argument("--env-name", "--env", dest="env_name", default="", help="Environment namespace for derived naming (e.g. dev, shared).")
    d.add_argument("--workspace-prefix", default="", help="Workspace prefix for derived naming.")
    d.add_argument("--name-prefix", default="", help="Override name_prefix token for derived naming.")
    d.add_argument("--context-id", default="", help="Override context_id token for derived naming.")
    d.add_argument("--root", default="", help="Runtime root for Terraform Cloud config discovery.")
    d.set_defaults(_handler=run_workspace_delete)


def _runtime_tfc_config(ns):
    root = str(getattr(ns, "root", "") or "").strip()
    env_name = str(getattr(ns, "env_name", "") or "").strip()
    runtime_root_env = str(os.environ.get("HYOPS_RUNTIME_ROOT") or "").strip()
    runtime_env = str(os.environ.get("HYOPS_ENV") or "").strip()

    if not (root or env_name or runtime_root_env or runtime_env):
        return None

    try:
        paths = resolve_runtime_paths(root or None, env_name or None)
    except Exception:
        return None

    config_path = runtime_config_path(paths.root)
    if not config_path.exists():
        return None

    try:
        return resolve_tfc_config(config_path=config_path)
    except Exception:
        return None


def _resolve_tfc_host(ns) -> str:
    explicit = str(getattr(ns, "host", "") or "").strip()
    if explicit:
        return explicit

    env_value = str(os.environ.get("TFC_HOST") or "").strip()
    if env_value:
        return env_value

    cfg = _runtime_tfc_config(ns)
    if cfg is not None and str(cfg.host or "").strip():
        return str(cfg.host).strip()

    return DEFAULT_TFC_HOST


def _resolve_tfc_org(ns) -> str:
    explicit = str(getattr(ns, "org", "") or "").strip()
    if explicit:
        return explicit

    env_value = str(os.environ.get("TFC_ORG") or "").strip()
    if env_value:
        return env_value

    cfg = _runtime_tfc_config(ns)
    if cfg is not None and str(cfg.org or "").strip():
        return str(cfg.org).strip()

    return ""


def _resolve_tfc_credentials_file(ns) -> Path:
    explicit = str(getattr(ns, "credentials_file", "") or "").strip()
    if explicit:
        return Path(explicit).expanduser().resolve()

    env_value = str(os.environ.get("TFC_CREDENTIALS_FILE") or "").strip()
    if env_value:
        return Path(env_value).expanduser().resolve()

    cfg = _runtime_tfc_config(ns)
    if cfg is not None:
        return Path(cfg.credentials_file).expanduser().resolve()

    return Path(DEFAULT_TFC_CREDENTIALS_FILE).expanduser().resolve()


def run_workspace_mode(ns) -> int:
    argv = [
        str(ns.workspace_name),
        _resolve_tfc_org(ns),
        str(ns.execution_mode),
        "--host",
        _resolve_tfc_host(ns),
        "--credentials-file",
        str(_resolve_tfc_credentials_file(ns)),
    ]
    if str(ns.description or "").strip():
        argv += ["--description", str(ns.description)]
    if bool(getattr(ns, "strict", False)):
        argv.append("--strict")
    if bool(getattr(ns, "json", False)):
        argv.append("--json")

    try:
        return int(configure_workspace_mode_main(argv))
    except SystemExit as e:
        return _exit_code_from_system_exit(e)
    except Exception as e:
        print(f"ERR: failed to enforce workspace mode: {e}")
        return INTERNAL_ERROR


def _workspace_name_from_args(ns) -> tuple[str, str]:
    explicit = str(getattr(ns, "workspace_name", "") or "").strip()
    if explicit:
        return explicit, ""

    provider = str(getattr(ns, "provider", "") or "").strip()
    module_ref = str(getattr(ns, "module_ref", "") or "").strip()
    pack_id = str(getattr(ns, "pack_id", "") or "").strip()
    if not (provider and module_ref and pack_id):
        return (
            "",
            "workspace_name is required, or provide --provider, --module-ref, and --pack-id to derive one",
        )

    inputs: dict[str, object] = {}
    if str(getattr(ns, "name_prefix", "") or "").strip():
        inputs["name_prefix"] = str(getattr(ns, "name_prefix")).strip()
    if str(getattr(ns, "context_id", "") or "").strip():
        inputs["context_id"] = str(getattr(ns, "context_id")).strip()

    env_map: dict[str, str] = {}
    if str(getattr(ns, "workspace_prefix", "") or "").strip():
        env_map["WORKSPACE_PREFIX"] = str(getattr(ns, "workspace_prefix")).strip()
    if str(getattr(ns, "env_name", "") or "").strip():
        env_map["HYOPS_ENV"] = str(getattr(ns, "env_name")).strip()

    ws_name, err = derive_workspace_name(
        provider=provider,
        module_ref=module_ref,
        pack_id=pack_id,
        inputs=inputs,
        env=env_map,
        env_name=str(getattr(ns, "env_name", "") or "").strip(),
        naming_policy=None,
    )
    return ws_name, err


def _log_workspace_ensure(result: dict[str, object]) -> None:
    status = str(result.get("status") or "unknown")
    msg = str(result.get("message") or "")
    ws = str(result.get("workspace_name") or "")
    mode = str(result.get("execution_mode") or "")

    if status == "created":
        print(f"[TFC Workspace] Created: {ws} ({mode})")
        return
    if status == "updated":
        print(f"[TFC Workspace] Updated: {ws} -> {mode}")
        return
    if status == "unchanged":
        print(f"[TFC Workspace] Exists: {ws} ({mode})")
        return

    print(f"[TFC Workspace] {status}")
    if ws:
        print(f"[TFC Workspace] workspace={ws}")
    if msg:
        print(f"[TFC Workspace] {msg}")


def _log_workspace_delete(result: dict[str, object]) -> None:
    status = str(result.get("status") or "unknown")
    msg = str(result.get("message") or "")
    ws = str(result.get("workspace_name") or "")
    force = bool(result.get("force"))

    if status == "deleted":
        mode = "force-deleted" if force else "deleted"
        print(f"[TFC Workspace] {mode}: {ws}")
        return
    if status == "not_found":
        print(f"[TFC Workspace] absent: {ws}")
        return

    print(f"[TFC Workspace] {status}")
    if ws:
        print(f"[TFC Workspace] workspace={ws}")
    if msg:
        print(f"[TFC Workspace] {msg}")


def run_workspace_delete(ns) -> int:
    ws_name, ws_err = _workspace_name_from_args(ns)
    if ws_err:
        print(f"ERR: {ws_err}")
        return 2

    result = delete_workspace(
        host=_resolve_tfc_host(ns),
        org=_resolve_tfc_org(ns),
        workspace_name=ws_name,
        credentials_file=_resolve_tfc_credentials_file(ns),
        force=bool(getattr(ns, "force", False)),
    )

    if bool(getattr(ns, "json", False)):
        print(json.dumps(result, indent=2, sort_keys=True))
    else:
        _log_workspace_delete(result)
        print(f"[TFC Workspace] resolved_name={ws_name}")

    if bool(result.get("ok")):
        return 0
    return 2 if bool(getattr(ns, "strict", False)) else 0


def run_workspace_ensure(ns) -> int:
    ws_name, ws_err = _workspace_name_from_args(ns)
    if ws_err:
        print(f"ERR: {ws_err}")
        return 2

    execution_mode = str(getattr(ns, "execution_mode", "local") or "local").strip()
    description = str(getattr(ns, "description", "") or "").strip() or default_workspace_description(execution_mode)

    result = ensure_workspace(
        host=_resolve_tfc_host(ns),
        org=_resolve_tfc_org(ns),
        workspace_name=ws_name,
        execution_mode=execution_mode,
        credentials_file=_resolve_tfc_credentials_file(ns),
        description=description,
    )

    if bool(getattr(ns, "json", False)):
        print(json.dumps(result, indent=2, sort_keys=True))
    else:
        _log_workspace_ensure(result)
        # Always show the resolved/derived name for operator transparency.
        print(f"[TFC Workspace] resolved_name={ws_name}")

    if bool(result.get("ok")):
        return 0
    return 2 if bool(getattr(ns, "strict", False)) else 0


__all__ = ["add_tfc_subparser", "run_workspace_mode", "run_workspace_ensure"]
