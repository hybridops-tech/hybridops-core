"""
purpose: Packer image driver for HybridOps.Core.
Architecture Decision: ADR-N/A (images packer driver)
maintainer: HybridOps.Studio
"""

from __future__ import annotations

import os
import shutil
import time
from pathlib import Path
from typing import Any

from hyops.runtime.credentials import (
    apply_runtime_credential_env,
    available_credential_providers,
    parse_tfvars,
    provider_env_key,
)
from hyops.runtime.evidence import EvidenceWriter
from hyops.runtime.packs import resolve_pack_stack
from hyops.runtime.proc import run_capture_stream
from hyops.runtime.coerce import as_bool, as_non_negative_int, as_positive_int
from .proxmox_api import (
    proxmox_agent_get_osinfo as _proxmox_agent_get_osinfo,
    proxmox_agent_wait_first_ipv4 as _proxmox_agent_wait_first_ipv4,
    proxmox_clone_vm as _proxmox_clone_vm,
    proxmox_name_exists as _proxmox_name_exists,
    proxmox_pick_free_vmid as _proxmox_pick_free_vmid,
    proxmox_pool_exists as _proxmox_pool_exists,
    proxmox_resolve_vmid_by_name as _proxmox_resolve_vmid_by_name,
    proxmox_start_vm as _proxmox_start_vm,
    proxmox_vmid_exists as _proxmox_vmid_exists,
    purge_template_vm as _purge_template_vm,
)
from .settings import (
    load_pack_config as _load_pack_config,
    load_profile as _load_profile,
    resolve_credential_contract as _resolve_credential_contract,
    resolve_packer_settings as _resolve_packer_settings,
    resolve_required_credentials as _resolve_required_credentials,
    resolve_template_key as _resolve_template_key,
    resolve_timeout as _resolve_timeout,
)
from .runtime_vars import map_runtime_vars as _map_runtime_vars
from .render import (
    cleanup_files as _cleanup_files,
    derive_password_hash as _derive_password_hash,
    render_unattended_templates as _render_unattended_templates,
    sync_shared_hcl as _sync_shared_hcl,
    write_runtime_vars as _write_runtime_vars,
)


_DRIVER_DIR = Path(__file__).resolve().parent
_PROFILES_DIR = _DRIVER_DIR / "profiles"


def _fail(ev: EvidenceWriter, result: dict[str, Any], msg: str) -> dict[str, Any]:
    log_path = (ev.dir / "packer.log").resolve()
    if log_path.exists() and "open:" not in str(msg):
        msg = f"{msg} (open: {log_path})"
    result["status"] = "error"
    result["error"] = msg
    ev.write_json("driver_result.json", result)
    return result


def _as_dict(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return dict(value)
    return {}


def _resolve_post_build_smoke_config(inputs: dict[str, Any], template_key: str) -> dict[str, Any]:
    raw = _as_dict(inputs.get("post_build_smoke"))
    enabled = as_bool(raw.get("enabled"), default=True)
    required = as_bool(raw.get("required"), default=False)
    timeout_s = as_positive_int(raw.get("timeout_s"))
    if timeout_s is None:
        timeout_s = 600 if "windows" in str(template_key or "").lower() else 300
    clone_timeout_s = as_positive_int(raw.get("clone_timeout_s")) or 900
    start_vmid = as_positive_int(raw.get("vmid_range_start")) or 990000
    end_vmid = as_positive_int(raw.get("vmid_range_end")) or 990999
    return {
        "enabled": bool(enabled),
        "required": bool(required),
        "timeout_s": int(timeout_s),
        "clone_timeout_s": int(clone_timeout_s),
        "vmid_range_start": int(start_vmid),
        "vmid_range_end": int(end_vmid),
    }


def _run_post_build_smoke(
    *,
    ev: EvidenceWriter,
    proxmox_url: str,
    proxmox_node: str,
    proxmox_token_id: str,
    proxmox_token_secret: str,
    skip_tls: bool,
    template_vmid: int,
    template_key: str,
    template_name: str,
    run_id: str,
    smoke_cfg: dict[str, Any],
) -> tuple[dict[str, Any], str]:
    summary: dict[str, Any] = {
        "enabled": True,
        "required": bool(smoke_cfg.get("required") is True),
        "template_key": template_key,
        "template_name": template_name,
        "template_vmid": int(template_vmid),
        "status": "running",
        "steps": [],
        "config": {
            "timeout_s": int(smoke_cfg.get("timeout_s") or 300),
            "clone_timeout_s": int(smoke_cfg.get("clone_timeout_s") or 900),
            "vmid_range_start": int(smoke_cfg.get("vmid_range_start") or 990000),
            "vmid_range_end": int(smoke_cfg.get("vmid_range_end") or 990999),
        },
    }

    temp_vmid = 0
    temp_name = ""

    def _step(name: str, status: str, **extra: Any) -> None:
        entry = {"step": name, "status": status}
        for k, v in extra.items():
            entry[k] = v
        summary["steps"].append(entry)

    try:
        picked, pick_err = _proxmox_pick_free_vmid(
            proxmox_url=proxmox_url,
            proxmox_node=proxmox_node,
            proxmox_token_id=proxmox_token_id,
            proxmox_token_secret=proxmox_token_secret,
            skip_tls=skip_tls,
            start_vmid=int(smoke_cfg.get("vmid_range_start") or 990000),
            end_vmid=int(smoke_cfg.get("vmid_range_end") or 990999),
        )
        if pick_err:
            _step("pick_vmid", "error", error=pick_err)
            summary["status"] = "error"
            summary["error"] = pick_err
            return summary, pick_err
        if picked is None:
            msg = "smoke vmid picker returned no VMID"
            _step("pick_vmid", "error", error=msg)
            summary["status"] = "error"
            summary["error"] = msg
            return summary, msg
        temp_vmid = int(picked)
        temp_name = f"hyops-template-smoke-{template_key}-{str(run_id or '')[-6:]}".replace(".", "-").lower()
        _step("pick_vmid", "ok", smoke_vmid=temp_vmid, smoke_name=temp_name)

        clone_meta, clone_err = _proxmox_clone_vm(
            proxmox_url=proxmox_url,
            proxmox_node=proxmox_node,
            proxmox_token_id=proxmox_token_id,
            proxmox_token_secret=proxmox_token_secret,
            skip_tls=skip_tls,
            source_vmid=int(template_vmid),
            new_vmid=int(temp_vmid),
            name=temp_name,
            full=True,
            timeout_s=int(smoke_cfg.get("clone_timeout_s") or 900),
        )
        if clone_err:
            _step("clone", "error", error=clone_err, meta=clone_meta)
            summary["status"] = "error"
            summary["error"] = clone_err
            return summary, clone_err
        _step("clone", "ok", meta=clone_meta)

        start_meta, start_err = _proxmox_start_vm(
            proxmox_url=proxmox_url,
            proxmox_node=proxmox_node,
            proxmox_token_id=proxmox_token_id,
            proxmox_token_secret=proxmox_token_secret,
            skip_tls=skip_tls,
            vmid=int(temp_vmid),
            timeout_s=120,
        )
        if start_err:
            _step("start", "error", error=start_err, meta=start_meta)
            summary["status"] = "error"
            summary["error"] = start_err
            return summary, start_err
        _step("start", "ok", meta=start_meta)

        ip_addr, agent_net_meta, ip_err = _proxmox_agent_wait_first_ipv4(
            proxmox_url=proxmox_url,
            proxmox_node=proxmox_node,
            proxmox_token_id=proxmox_token_id,
            proxmox_token_secret=proxmox_token_secret,
            skip_tls=skip_tls,
            vmid=int(temp_vmid),
            timeout_s=int(smoke_cfg.get("timeout_s") or 300),
            poll_s=5.0,
        )
        if ip_err:
            _step("guest_agent_ip", "error", error=ip_err)
            if agent_net_meta:
                summary["guest_agent_network"] = agent_net_meta
            summary["status"] = "error"
            summary["error"] = ip_err
            return summary, ip_err
        summary["smoke_vm_ip"] = ip_addr
        _step("guest_agent_ip", "ok", ip=ip_addr)
        if agent_net_meta:
            summary["guest_agent_network"] = agent_net_meta

        osinfo, osinfo_err = _proxmox_agent_get_osinfo(
            proxmox_url=proxmox_url,
            proxmox_node=proxmox_node,
            proxmox_token_id=proxmox_token_id,
            proxmox_token_secret=proxmox_token_secret,
            skip_tls=skip_tls,
            vmid=int(temp_vmid),
        )
        if osinfo_err:
            _step("guest_agent_osinfo", "warn", warning=osinfo_err)
            summary["warnings"] = list(summary.get("warnings") or []) + [osinfo_err]
        elif osinfo:
            summary["guest_osinfo"] = osinfo
            pretty = str(osinfo.get("pretty-name") or osinfo.get("name") or "").strip()
            _step("guest_agent_osinfo", "ok", pretty_name=pretty)

        summary["status"] = "ok"
        summary["smoke_vmid"] = int(temp_vmid)
        summary["smoke_name"] = temp_name
        return summary, ""
    finally:
        if temp_vmid > 0:
            purge_warnings, purge_err = _purge_template_vm(
                proxmox_url=proxmox_url,
                proxmox_node=proxmox_node,
                proxmox_token_id=proxmox_token_id,
                proxmox_token_secret=proxmox_token_secret,
                skip_tls=skip_tls,
                vmid=int(temp_vmid),
            )
            cleanup_entry: dict[str, Any] = {"step": "cleanup", "smoke_vmid": int(temp_vmid)}
            if purge_warnings:
                cleanup_entry["warnings"] = list(purge_warnings)
            if purge_err:
                cleanup_entry["status"] = "error"
                cleanup_entry["error"] = purge_err
                summary["cleanup_error"] = purge_err
            else:
                cleanup_entry["status"] = "ok"
            summary["steps"].append(cleanup_entry)
            summary["smoke_vmid"] = int(temp_vmid)
            if temp_name:
                summary["smoke_name"] = temp_name


def run(request: dict[str, Any]) -> dict[str, Any]:
    evidence_dir = Path(str(request.get("evidence_dir") or "")).expanduser().resolve()
    evidence_dir.mkdir(parents=True, exist_ok=True)
    ev = EvidenceWriter(evidence_dir)

    run_id = str(request.get("run_id") or "").strip()
    module_ref = str(request.get("module_ref") or "").strip()
    execution = _as_dict(request.get("execution"))
    runtime = _as_dict(request.get("runtime"))

    command_name = str(request.get("command") or "apply").strip().lower()
    if command_name == "deploy":
        command_name = "apply"
    lifecycle_command = str(request.get("lifecycle_command") or "").strip().lower()
    destroy_intent = command_name == "destroy" or (command_name == "preflight" and lifecycle_command == "destroy")
    if command_name not in ("apply", "plan", "validate", "preflight", "destroy"):
        return _fail(
            ev,
            {"status": "error", "run_id": run_id, "normalized_outputs": {}, "warnings": []},
            f"unsupported command for images/packer driver: {command_name}",
        )

    driver_ref = str(execution.get("driver") or "").strip()
    profile_ref = str(execution.get("profile") or "").strip()
    pack_id = str(execution.get("pack_id") or "").strip()

    result: dict[str, Any] = {
        "status": "error",
        "run_id": run_id,
        "command": command_name,
        "driver": {"ref": driver_ref, "profile": profile_ref, "pack_id": pack_id},
        "normalized_outputs": {},
        "warnings": [],
    }

    if not run_id:
        return _fail(ev, result, "missing run_id")
    if not pack_id:
        return _fail(ev, result, "missing execution.pack_id")
    if not profile_ref:
        return _fail(ev, result, "missing execution.profile")

    root_raw = str(runtime.get("root") or "").strip()
    if not root_raw:
        return _fail(ev, result, "missing runtime.root")
    runtime_root = Path(root_raw).expanduser().resolve()

    inputs = _as_dict(request.get("inputs"))

    profile, profile_path, profile_error = _load_profile(profile_ref, _PROFILES_DIR)
    if profile_error:
        return _fail(ev, result, profile_error)

    packer_bin, init_args, validate_args, build_args = _resolve_packer_settings(profile)
    timeout_s = _resolve_timeout(profile)
    if not shutil.which(packer_bin):
        return _fail(ev, result, f"packer binary not found: {packer_bin}")

    try:
        pack_stack = resolve_pack_stack(
            driver_ref=driver_ref,
            pack_id=pack_id,
            require_stack_files=("packer.build.yml",),
        )
    except Exception as exc:
        return _fail(ev, result, f"pack resolution failed: {exc}")

    required_credentials = _resolve_required_credentials(request)
    creds_dir_raw = str(runtime.get("credentials_dir") or "").strip()
    credential_env = apply_runtime_credential_env(
        os.environ.copy(),
        creds_dir_raw if creds_dir_raw else None,
    )

    available_provider_keys = available_credential_providers(credential_env)
    missing_credentials: list[str] = []
    for provider in required_credentials:
        if provider_env_key(provider) not in available_provider_keys:
            missing_credentials.append(provider)
    if missing_credentials:
        cred_path_hint = creds_dir_raw if creds_dir_raw else "<runtime.credentials_dir>"
        env_name = str(runtime.get("env") or "").strip()
        env_arg = f" --env {env_name}" if env_name else ""
        init_hint = f"run: hyops init proxmox{env_arg} --bootstrap --proxmox-ip <PROXMOX_IP>"
        return _fail(
            ev,
            result,
            f"missing required credentials: {', '.join(missing_credentials)} "
            f"(expected credentials in {cred_path_hint}); {init_hint}",
        )

    proxmox_provider = provider_env_key("proxmox")
    proxmox_path_raw = str(
        credential_env.get(f"HYOPS_{proxmox_provider}_TFVARS")
        or credential_env.get(f"HYOPS_{proxmox_provider}_CREDENTIALS_FILE")
        or ""
    ).strip()
    proxmox_tfvars = parse_tfvars(Path(proxmox_path_raw).expanduser()) if proxmox_path_raw else {}

    required_tfvars = _resolve_credential_contract(profile, "proxmox")
    if required_tfvars:
        missing_tfvars = [k for k in required_tfvars if str(proxmox_tfvars.get(k) or "").strip() == ""]
        if missing_tfvars:
            env_name = str(runtime.get("env") or "").strip()
            env_arg = f" --env {env_name}" if env_name else ""
            source_hint = proxmox_path_raw if proxmox_path_raw else "<HYOPS_PROXMOX_TFVARS>"
            extra_help: list[str] = []
            missing_set = set(missing_tfvars)
            if "ssh_public_key" in missing_set:
                extra_help.append("ssh_public_key: set proxmox.ssh_public_key or run ssh-keygen")
            if "http_bind_address" in missing_set:
                extra_help.append("http_bind_address: set proxmox.http_bind_address or pass --http-bind-address")
            if "http_port" in missing_set:
                extra_help.append("http_port: set proxmox.http_port or pass --http-port")
            extra = f" ({'; '.join(extra_help)})" if extra_help else ""
            return _fail(
                ev,
                result,
                f"proxmox credential contract failed; missing tfvars keys: {', '.join(missing_tfvars)} "
                f"(source: {source_hint}){extra}; run: hyops init proxmox{env_arg} --bootstrap --proxmox-ip <PROXMOX_IP>",
            )

    work_root_raw = str(runtime.get("work_dir") or "").strip()
    work_root = Path(work_root_raw).expanduser().resolve() if work_root_raw else (runtime_root / "work")
    module_id = module_ref.replace("/", "__") if module_ref else "unknown_module"
    workdir = work_root / module_id / run_id
    stack_dst = workdir / "stack"

    try:
        workdir.mkdir(parents=True, exist_ok=True)
        if stack_dst.exists():
            shutil.rmtree(stack_dst)
        shutil.copytree(pack_stack.stack_dir, stack_dst)
    except Exception as exc:
        return _fail(ev, result, f"workdir setup failed: {exc}")

    pack_cfg, pack_cfg_error = _load_pack_config(stack_dst / "packer.build.yml")
    if pack_cfg_error:
        return _fail(ev, result, pack_cfg_error)

    template_key, template_cfg, template_error = _resolve_template_key(inputs, pack_cfg)
    if template_error:
        return _fail(ev, result, template_error)

    work_dir_rel = str(template_cfg.get("working_dir") or ".").strip() or "."
    template_work_dir = (stack_dst / work_dir_rel).resolve()
    try:
        template_work_dir.relative_to(stack_dst)
    except Exception:
        return _fail(ev, result, f"template working_dir escaped pack root: {work_dir_rel}")
    if not template_work_dir.is_dir():
        return _fail(ev, result, f"template working_dir not found: {template_work_dir}")

    var_file_rel = str(template_cfg.get("var_file") or "").strip()
    if not var_file_rel:
        return _fail(ev, result, f"template {template_key} missing var_file")
    var_file_path = (template_work_dir / var_file_rel).resolve()
    if not var_file_path.exists():
        return _fail(ev, result, f"template var_file not found: {var_file_path}")

    runtime_vars, runtime_vars_error = _map_runtime_vars(
        inputs,
        proxmox_tfvars,
        template_key=template_key,
    )
    if runtime_vars_error:
        return _fail(ev, result, runtime_vars_error)

    base_vars = parse_tfvars(var_file_path)
    vmid = as_non_negative_int(runtime_vars.get("vmid"))
    if vmid is None:
        vmid = as_non_negative_int(base_vars.get("vmid"))
    if vmid is None:
        vmid = 0
    runtime_vars["vmid"] = int(vmid)

    template_name = str(runtime_vars.get("name") or "").strip()
    if not template_name:
        template_name = f"{template_key}-template"
    runtime_vars["name"] = template_name

    proxmox_url = str(runtime_vars.get("proxmox_url") or "").strip()
    proxmox_node = str(runtime_vars.get("proxmox_node") or "").strip()
    proxmox_token_id = str(runtime_vars.get("proxmox_token_id") or "").strip()
    proxmox_token_secret = str(runtime_vars.get("proxmox_token_secret") or "").strip()
    skip_tls = bool(runtime_vars.get("proxmox_skip_tls") is True)
    proxmox_pool = str(runtime_vars.get("pool") or "").strip()

    if not destroy_intent:
        if not proxmox_url or not proxmox_node or not proxmox_token_id or not proxmox_token_secret:
            return _fail(
                ev,
                result,
                "apply requires proxmox_url/proxmox_node/proxmox_token_id/proxmox_token_secret",
            )

        if proxmox_pool:
            pool_exists, pool_err = _proxmox_pool_exists(
                proxmox_url=proxmox_url,
                proxmox_token_id=proxmox_token_id,
                proxmox_token_secret=proxmox_token_secret,
                skip_tls=skip_tls,
                pool=proxmox_pool,
            )
            if pool_err:
                return _fail(
                    ev,
                    result,
                    (
                        f"proxmox pool check failed for inputs.pool={proxmox_pool!r}: {pool_err}. "
                        "Set inputs.pool to an existing Proxmox pool (accessible by the API token), or unset inputs.pool."
                    ),
                )
            if not pool_exists:
                return _fail(
                    ev,
                    result,
                    (
                        f"inputs.pool={proxmox_pool!r} does not exist on Proxmox (or is not visible to the API token). "
                        "Set inputs.pool to an existing Proxmox pool, or unset inputs.pool."
                    ),
                )

        rebuild_if_exists = bool(inputs.get("rebuild_if_exists") is True)

        if int(vmid) > 0:
            exists, exists_err = _proxmox_vmid_exists(
                proxmox_url=proxmox_url,
                proxmox_node=proxmox_node,
                proxmox_token_id=proxmox_token_id,
                proxmox_token_secret=proxmox_token_secret,
                skip_tls=skip_tls,
                vmid=int(vmid),
            )
            if exists_err:
                return _fail(ev, result, f"proxmox vmid check failed: {exists_err}")
            if exists:
                if rebuild_if_exists and command_name == "apply":
                    purge_warnings, purge_error = _purge_template_vm(
                        proxmox_url=proxmox_url,
                        proxmox_node=proxmox_node,
                        proxmox_token_id=proxmox_token_id,
                        proxmox_token_secret=proxmox_token_secret,
                        skip_tls=skip_tls,
                        vmid=int(vmid),
                    )
                    if purge_error:
                        return _fail(ev, result, purge_error)
                    if purge_warnings:
                        result["warnings"] = list(purge_warnings)
                elif rebuild_if_exists:
                    result["warnings"] = [
                        f"template vmid={int(vmid)} exists; rebuild_if_exists=true will purge before apply"
                    ]
                else:
                    # Idempotent apply: if the template already exists, do not rebuild unless requested.
                    if command_name in ("apply", "preflight"):
                        result["status"] = "ok"
                        result["warnings"] = [
                            (
                                f"template vmid={int(vmid)} already exists on node={proxmox_node}; "
                                f"skipping build (set inputs.rebuild_if_exists=true to rebuild)"
                            )
                        ]
                        published_outputs = {
                            "template_key": template_key,
                            "template_vm_id": int(vmid),
                            "template_name": template_name,
                            "template_vm_ids": {template_key: int(vmid)},
                            "templates": {template_key: {"vm_id": int(vmid), "name": template_name}},
                        }
                        result["normalized_outputs"] = {
                            "published_outputs": published_outputs,
                            "workdir": str(workdir),
                            "command": command_name,
                            "skipped": True,
                            "reason": "template-exists",
                        }
                        ev.write_json("driver_result.json", result)
                        return result

                    result["warnings"] = [
                        (
                            f"template vmid={int(vmid)} already exists on node={proxmox_node}; "
                            f"no build will be performed unless inputs.rebuild_if_exists=true"
                        )
                    ]
        else:
            name_exists, name_err = _proxmox_name_exists(
                proxmox_url=proxmox_url,
                proxmox_node=proxmox_node,
                proxmox_token_id=proxmox_token_id,
                proxmox_token_secret=proxmox_token_secret,
                skip_tls=skip_tls,
                name=template_name,
            )
            if name_err:
                return _fail(ev, result, f"proxmox name check failed: {name_err}")
            if name_exists:
                if rebuild_if_exists:
                    resolved, resolve_err = _proxmox_resolve_vmid_by_name(
                        proxmox_url=proxmox_url,
                        proxmox_node=proxmox_node,
                        proxmox_token_id=proxmox_token_id,
                        proxmox_token_secret=proxmox_token_secret,
                        skip_tls=skip_tls,
                        name=template_name,
                    )
                    if resolve_err:
                        return _fail(ev, result, f"failed to resolve template vmid by name: {resolve_err}")
                    if resolved is None:
                        return _fail(
                            ev,
                            result,
                            f"template name={template_name} exists but vmid could not be resolved; set inputs.vmid explicitly",
                        )
                    if command_name == "apply":
                        purge_warnings, purge_error = _purge_template_vm(
                            proxmox_url=proxmox_url,
                            proxmox_node=proxmox_node,
                            proxmox_token_id=proxmox_token_id,
                            proxmox_token_secret=proxmox_token_secret,
                            skip_tls=skip_tls,
                            vmid=int(resolved),
                        )
                        if purge_error:
                            return _fail(ev, result, purge_error)
                        if purge_warnings:
                            result["warnings"] = list(purge_warnings)
                    else:
                        result["warnings"] = [
                            f"template name={template_name} exists; rebuild_if_exists=true will purge before apply"
                        ]
                else:
                    # Idempotent apply: if the template already exists, do not rebuild unless requested.
                    if command_name in ("apply", "preflight"):
                        resolved, resolve_err = _proxmox_resolve_vmid_by_name(
                            proxmox_url=proxmox_url,
                            proxmox_node=proxmox_node,
                            proxmox_token_id=proxmox_token_id,
                            proxmox_token_secret=proxmox_token_secret,
                            skip_tls=skip_tls,
                            name=template_name,
                        )
                        if resolve_err:
                            return _fail(ev, result, f"failed to resolve template vmid by name: {resolve_err}")
                        if resolved is None:
                            return _fail(
                                ev,
                                result,
                                f"template name={template_name} exists but vmid could not be resolved; set inputs.vmid explicitly",
                            )

                        result["status"] = "ok"
                        result["warnings"] = [
                            (
                                f"template name={template_name} already exists on node={proxmox_node}; "
                                f"skipping build (set inputs.rebuild_if_exists=true to rebuild)"
                            )
                        ]
                        published_outputs = {
                            "template_key": template_key,
                            "template_vm_id": int(resolved),
                            "template_name": template_name,
                            "template_vm_ids": {template_key: int(resolved)},
                            "templates": {template_key: {"vm_id": int(resolved), "name": template_name}},
                        }
                        result["normalized_outputs"] = {
                            "published_outputs": published_outputs,
                            "workdir": str(workdir),
                            "command": command_name,
                            "skipped": True,
                            "reason": "template-exists",
                        }
                        ev.write_json("driver_result.json", result)
                        return result

                    result["warnings"] = [
                        (
                            f"template name={template_name} already exists on node={proxmox_node}; "
                            f"no build will be performed unless inputs.rebuild_if_exists=true"
                        )
                    ]

    if destroy_intent:
        if not proxmox_url or not proxmox_node or not proxmox_token_id or not proxmox_token_secret:
            return _fail(
                ev,
                result,
                "destroy requires proxmox_url/proxmox_node/proxmox_token_id/proxmox_token_secret",
            )

        resolved_destroy_vmid = int(vmid)
        destroy_warnings: list[str] = []
        if resolved_destroy_vmid == 0:
            resolved, resolve_err = _proxmox_resolve_vmid_by_name(
                proxmox_url=proxmox_url,
                proxmox_node=proxmox_node,
                proxmox_token_id=proxmox_token_id,
                proxmox_token_secret=proxmox_token_secret,
                skip_tls=skip_tls,
                name=template_name,
            )
            if resolve_err:
                return _fail(ev, result, f"failed to resolve template vmid by name: {resolve_err}")
            if resolved is None:
                destroy_warnings.append(f"template name={template_name} not found; nothing to purge")
            else:
                resolved_destroy_vmid = int(resolved)

        if command_name == "preflight":
            if destroy_warnings:
                result["warnings"] = list(destroy_warnings)
            result["status"] = "ok"
            result["normalized_outputs"] = {
                "preflight": {
                    "module_ref": module_ref,
                    "profile_ref": profile_ref,
                    "pack_id": pack_id,
                    "template_key": template_key,
                    "template_vm_id": int(resolved_destroy_vmid),
                    "template_name": template_name,
                    "lifecycle_command": "destroy",
                }
            }
            ev.write_json("driver_result.json", result)
            return result

        if resolved_destroy_vmid == 0:
            result["status"] = "ok"
            result["warnings"] = list(destroy_warnings)
            result["normalized_outputs"] = {
                "outputs": {
                    "template_key": template_key,
                    "template_vm_id": 0,
                    "template_name": template_name,
                },
                "workdir": str(workdir),
                "command": "destroy",
            }
            ev.write_json("driver_result.json", result)
            return result

        purge_warnings, purge_error = _purge_template_vm(
            proxmox_url=proxmox_url,
            proxmox_node=proxmox_node,
            proxmox_token_id=proxmox_token_id,
            proxmox_token_secret=proxmox_token_secret,
            skip_tls=bool(runtime_vars.get("proxmox_skip_tls") is True),
            vmid=int(resolved_destroy_vmid),
        )
        if purge_error:
            return _fail(ev, result, purge_error)

        combined_warnings = list(destroy_warnings) + list(purge_warnings or [])
        if combined_warnings:
            result["warnings"] = combined_warnings
        result["status"] = "ok"
        result["normalized_outputs"] = {
            "outputs": {
                "template_key": template_key,
                "template_vm_id": int(resolved_destroy_vmid),
                "template_name": template_name,
            },
            "workdir": str(workdir),
            "command": "destroy",
        }
        ev.write_json("driver_result.json", result)
        return result

    ssh_public_key = str(runtime_vars.get("ssh_public_key") or "").strip()
    if not str(runtime_vars.get("ssh_password_hash") or "").strip():
        try:
            runtime_vars["ssh_password_hash"] = _derive_password_hash()
        except Exception as exc:
            return _fail(ev, result, str(exc))

    admin_user = str(inputs.get("admin_user") or runtime_vars.get("ssh_username") or "hybridops").strip()
    if not admin_user:
        return _fail(ev, result, "admin_user resolved to empty value")
    try:
        _render_unattended_templates(
            template_work_dir,
            admin_user=admin_user,
            ssh_public_key=ssh_public_key,
            ssh_password_hash=str(runtime_vars.get("ssh_password_hash") or "").strip(),
        )
    except Exception as exc:
        return _fail(ev, result, f"failed to render unattended templates: {exc}")

    runtime_vars_path = (template_work_dir / ".hyops.runtime.auto.pkrvars.hcl").resolve()
    try:
        _write_runtime_vars(runtime_vars_path, runtime_vars)
    except Exception as exc:
        return _fail(ev, result, f"failed to write runtime vars: {exc}")

    ev.write_json(
        "meta.json",
        {
            "run_id": run_id,
            "command": command_name,
            "module_ref": module_ref,
            "profile_ref": profile_ref,
            "profile_path": str(profile_path),
            "pack_id": pack_id,
            "pack_stack": str(pack_stack.stack_dir),
            "workdir": str(workdir),
            "template_work_dir": str(template_work_dir),
            "template_key": template_key,
            "template_var_file": str(var_file_path),
            "runtime_var_file": str(runtime_vars_path),
            "required_credentials": required_credentials,
            "available_credentials": sorted([k.lower() for k in available_provider_keys]),
        },
    )

    if command_name == "preflight":
        result["status"] = "ok"
        result["normalized_outputs"] = {
            "preflight": {
                "module_ref": module_ref,
                "profile_ref": profile_ref,
                "pack_id": pack_id,
                "template_key": template_key,
                "template_vm_id": int(vmid),
                "template_name": template_name,
            }
        }
        ev.write_json("driver_result.json", result)
        return result

    build_only = str(template_cfg.get("build_only") or "").strip()

    shared_copies: list[Path] = []
    shared_dir = (stack_dst / "shared").resolve()
    sync_err = ""
    if shared_dir.is_dir():
        shared_copies, sync_err = _sync_shared_hcl(template_work_dir, shared_dir)
    if sync_err:
        return _fail(ev, result, sync_err)

    build_executed = False
    try:
        packer_log = (evidence_dir / "packer.log").resolve()

        init_cmd = [packer_bin, *init_args, "."]
        r_init = run_capture_stream(
            init_cmd,
            cwd=str(template_work_dir),
            env=os.environ.copy(),
            evidence_dir=evidence_dir,
            label="packer_init",
            timeout_s=timeout_s,
            redact=True,
            tee_path=packer_log,
        )
        if r_init.rc != 0:
            return _fail(ev, result, "packer init failed")

        validate_cmd = [packer_bin, *validate_args]
        if build_only:
            validate_cmd.append(f"-only={build_only}")
        validate_cmd.extend(["-var-file", str(var_file_path), "-var-file", str(runtime_vars_path), "."])
        r_validate = run_capture_stream(
            validate_cmd,
            cwd=str(template_work_dir),
            env=os.environ.copy(),
            evidence_dir=evidence_dir,
            label="packer_validate",
            timeout_s=timeout_s,
            redact=True,
            tee_path=packer_log,
        )
        if r_validate.rc != 0:
            return _fail(ev, result, "packer validate failed")

        if command_name == "apply":
            build_cmd = [packer_bin, *build_args]
            if build_only:
                build_cmd.append(f"-only={build_only}")
            build_cmd.extend(["-var-file", str(var_file_path), "-var-file", str(runtime_vars_path), "."])
            r_build = run_capture_stream(
                build_cmd,
                cwd=str(template_work_dir),
                env=os.environ.copy(),
                evidence_dir=evidence_dir,
                label="packer_build",
                timeout_s=timeout_s,
                redact=True,
                tee_path=packer_log,
            )
            if r_build.rc != 0:
                return _fail(ev, result, "packer build failed")
            build_executed = True
    except KeyboardInterrupt:
        return _fail(ev, result, "interrupted by user (Ctrl+C)")
    finally:
        _cleanup_files(shared_copies)

    resolved_vmid = int(vmid)
    if resolved_vmid == 0:
        deadline = time.time() + 60.0
        while time.time() < deadline:
            found, resolve_err = _proxmox_resolve_vmid_by_name(
                proxmox_url=proxmox_url,
                proxmox_node=proxmox_node,
                proxmox_token_id=proxmox_token_id,
                proxmox_token_secret=proxmox_token_secret,
                skip_tls=skip_tls,
                name=template_name,
            )
            if resolve_err:
                return _fail(ev, result, f"failed to resolve template vmid by name after build: {resolve_err}")
            if found is not None:
                resolved_vmid = int(found)
                break
            time.sleep(2.0)
        if resolved_vmid == 0:
            return _fail(
                ev,
                result,
                f"unable to resolve template vmid for name={template_name} after build; set inputs.vmid explicitly",
            )

    published_outputs = {
        "template_key": template_key,
        "template_vm_id": int(resolved_vmid),
        "template_name": template_name,
        "template_vm_ids": {template_key: int(resolved_vmid)},
        "templates": {template_key: {"vm_id": int(resolved_vmid), "name": template_name}},
    }

    post_build_smoke: dict[str, Any] | None = None
    smoke_cfg = _resolve_post_build_smoke_config(inputs, template_key)
    if command_name == "apply" and build_executed and bool(smoke_cfg.get("enabled")):
        smoke_summary, smoke_err = _run_post_build_smoke(
            ev=ev,
            proxmox_url=proxmox_url,
            proxmox_node=proxmox_node,
            proxmox_token_id=proxmox_token_id,
            proxmox_token_secret=proxmox_token_secret,
            skip_tls=skip_tls,
            template_vmid=int(resolved_vmid),
            template_key=template_key,
            template_name=template_name,
            run_id=run_id,
            smoke_cfg=smoke_cfg,
        )
        post_build_smoke = smoke_summary
        ev.write_json("template_smoke.json", smoke_summary)
        ev.write_text(
            "template_smoke.log",
            "\n".join([f"{step.get('step')} status={step.get('status')}" for step in smoke_summary.get("steps", [])]),
            redact_output=False,
        )
        if smoke_err:
            smoke_required = bool(smoke_cfg.get("required"))
            msg = (
                "post-build template smoke validation failed: "
                f"{smoke_err} (set inputs.post_build_smoke.required=false to warn-only, "
                "or inputs.post_build_smoke.enabled=false to disable)"
            )
            if smoke_required:
                return _fail(ev, result, msg)
            result["warnings"] = list(result.get("warnings") or []) + [msg]
    elif command_name == "apply" and build_executed:
        post_build_smoke = {"enabled": False, "status": "skipped"}

    result["status"] = "ok"
    result["normalized_outputs"] = {
        "published_outputs": published_outputs,
        "workdir": str(workdir),
        "command": command_name,
    }
    if post_build_smoke is not None:
        result["normalized_outputs"]["post_build_smoke"] = post_build_smoke
    ev.write_json("driver_result.json", result)
    return result
