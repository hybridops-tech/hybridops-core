"""hyops.drivers.config.ansible.driver

purpose: Ansible configuration driver for HybridOps.Core.
Architecture Decision: ADR-N/A (config ansible driver)
maintainer: HybridOps.Tech
"""

from __future__ import annotations

import json
import os
import shutil
import sys
from pathlib import Path
from typing import Any

import yaml

from hyops.runtime.credentials import (
    apply_runtime_credential_env,
    available_credential_providers,
    provider_env_key,
)
from hyops.runtime.module_state import read_module_state
from hyops.runtime.evidence import EvidenceWriter
from hyops.runtime.packs import resolve_pack_stack
from hyops.runtime.provider_bootstrap import gcp_bootstrap_guard_message
from hyops.runtime.coerce import as_bool, as_int
from hyops.runtime.source_roots import discover_core_root
from .config import (
    load_profile,
    resolve_ansible_cfg,
    resolve_policy_defaults,
    resolve_required_credentials,
    resolve_required_env,
)
from .connectivity import (
    apply_proxy_jump_auto,
    connectivity_check,
    rke2_image_preflight_check,
)
from .execution import build_playbook_argv, resolve_execution_args
from .inventory import write_inventory
from .playbook import resolve_playbook_file
from .process import run_capture_with_policy
from .results import ansible_error_hint, load_outputs
from .runtime_env import (
    configure_ansible_search_paths,
    ensure_hybridops_collections_available,
    materialize_ssh_private_key_from_env,
    merge_vault_env,
    missing_env,
    prepare_ansible_controller_env,
)


_DRIVER_DIR = Path(__file__).resolve().parent
_PROFILES_DIR = _DRIVER_DIR / "profiles"
_PGHA_MODULE_REFS = {"platform/postgresql-ha", "platform/onprem/postgresql-ha"}

def _resolve_hyops_executable() -> str:
    """Resolve a real hyops executable path for delegated local tasks."""
    try:
        sibling = (Path(sys.executable).expanduser().resolve().parent / "hyops").resolve()
        if sibling.exists() and os.access(sibling, os.X_OK):
            return str(sibling)
    except Exception:
        pass

    argv0 = str(getattr(sys, "argv", [""])[:1][0] or "").strip()
    if argv0:
        if "/" in argv0:
            try:
                candidate = Path(argv0).expanduser().resolve()
                if candidate.exists() and os.access(candidate, os.X_OK):
                    return str(candidate)
            except Exception:
                pass
        resolved = shutil.which(argv0)
        if resolved:
            candidate = Path(resolved).expanduser().resolve()
            if candidate.exists() and os.access(candidate, os.X_OK):
                return str(candidate)

    resolved = shutil.which("hyops")
    if resolved:
        candidate = Path(resolved).expanduser().resolve()
        if candidate.exists() and os.access(candidate, os.X_OK):
            return str(candidate)
    return "hyops"

def _fail(ev: EvidenceWriter, result: dict[str, Any], msg: str) -> dict[str, Any]:
    log_path = (ev.dir / "ansible.log").resolve()
    if log_path.exists() and "open:" not in str(msg):
        msg = f"{msg} (open: {log_path})"
    result["status"] = "error"
    result["error"] = msg
    ev.write_json("driver_result.json", result)
    return result


def _maybe_short_circuit_destroy_for_absent_inventory(
    *,
    ev: EvidenceWriter,
    result: dict[str, Any],
    runtime_root: Path,
    workdir: Path,
    outputs_path: Path,
    module_ref: str,
    command_name: str,
    inputs: dict[str, Any],
) -> dict[str, Any] | None:
    if command_name != "destroy":
        return None
    if module_ref not in _PGHA_MODULE_REFS:
        return None

    inventory_state_ref = str(inputs.get("inventory_state_ref") or "").strip()
    if not inventory_state_ref:
        return None

    try:
        state = read_module_state(runtime_root / "state", inventory_state_ref)
    except Exception:
        return None

    upstream_status = str(state.get("status") or "").strip().lower()
    if upstream_status not in {"destroyed", "absent"}:
        return None

    outputs = {"cap.db.postgresql_ha": "absent"}
    try:
        outputs_path.write_text(json.dumps(outputs), encoding="utf-8")
    except Exception as exc:
        return _fail(ev, result, f"failed to write destroy short-circuit outputs: {exc}")

    result.setdefault("warnings", []).append(
        f"skipped remote destroy because inventory_state_ref={inventory_state_ref} is already {upstream_status}"
    )
    result["status"] = "ok"
    result["normalized_outputs"] = {
        "command": command_name,
        "workdir": str(workdir),
        **outputs,
    }
    ev.write_json("driver_result.json", result)
    return result


def run(request: dict[str, Any]) -> dict[str, Any]:
    evidence_dir = Path(str(request.get("evidence_dir") or "")).expanduser().resolve()
    evidence_dir.mkdir(parents=True, exist_ok=True)
    ev = EvidenceWriter(evidence_dir)

    run_id = str(request.get("run_id") or "").strip()
    module_ref = str(request.get("module_ref") or "").strip()

    execution = request.get("execution")
    if not isinstance(execution, dict):
        execution = {}

    runtime = request.get("runtime")
    if not isinstance(runtime, dict):
        runtime = {}

    driver_ref = str(execution.get("driver") or "").strip()
    profile_ref = str(execution.get("profile") or "").strip()
    pack_id = str(execution.get("pack_id") or "").strip()

    command_name = str(request.get("command") or "apply").strip().lower()
    if command_name == "deploy":
        command_name = "apply"

    if command_name not in ("apply", "plan", "validate", "destroy", "preflight"):
        return _fail(
            ev,
            {"status": "error", "run_id": run_id, "normalized_outputs": {}, "warnings": []},
            f"unsupported command for ansible driver: {command_name}",
        )

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

    runtime_root_raw = str(runtime.get("root") or "").strip()
    if not runtime_root_raw:
        return _fail(ev, result, "missing runtime.root")

    runtime_root = Path(runtime_root_raw).expanduser().resolve()
    module_id = module_ref.replace("/", "__") if module_ref else "unknown_module"
    work_root_raw = str(runtime.get("work_dir") or "").strip()
    work_root = Path(work_root_raw).expanduser().resolve() if work_root_raw else (runtime_root / "work")
    workdir = work_root / module_id / run_id

    profile, profile_path_obj, profile_error = load_profile(profile_ref, _PROFILES_DIR)
    profile_path = str(profile_path_obj) if profile_path_obj else ""
    if profile_error:
        return _fail(ev, result, profile_error)

    timeout_s, retries, redact = resolve_policy_defaults(profile)
    ansible_cfg = resolve_ansible_cfg(profile)

    ansible_bin = ansible_cfg["bin"]
    if not shutil.which(ansible_bin):
        return _fail(ev, result, f"missing command: {ansible_bin}")

    try:
        resolved = resolve_pack_stack(
            driver_ref=driver_ref,
            pack_id=pack_id,
            require_stack_files=(ansible_cfg["playbook_file"],),
        )
    except Exception as exc:
        return _fail(
            ev,
            result,
            f"pack resolution failed: {exc} (set HYOPS_PACKS_ROOT to the directory containing 'packs/')",
        )

    pack_stack = resolved.stack_dir

    required_credentials = resolve_required_credentials(request)
    env = os.environ.copy()
    env["HYOPS_RUNTIME_ROOT"] = str(runtime_root)
    if not str(env.get("HYOPS_CORE_ROOT") or "").strip():
        core_root = discover_core_root()
        if core_root is not None:
            env["HYOPS_CORE_ROOT"] = str(core_root)

    env_name = str(runtime.get("env") or "").strip()
    if env_name and "HYOPS_ENV" not in env:
        env["HYOPS_ENV"] = env_name
    if not str(env.get("HYOPS_EXECUTABLE") or "").strip():
        env["HYOPS_EXECUTABLE"] = _resolve_hyops_executable()

    creds_raw = str(runtime.get("credentials_dir") or "").strip()
    credential_env = apply_runtime_credential_env(env, creds_raw if creds_raw else None)
    available_provider_keys = available_credential_providers(credential_env)
    available_credentials = sorted([p.lower() for p in available_provider_keys])

    missing_credentials: list[str] = []
    for provider in required_credentials:
        if provider_env_key(provider) not in available_provider_keys:
            missing_credentials.append(provider)

    credential_error = ""
    if missing_credentials:
        cred_path_hint = creds_raw if creds_raw else "<runtime.credentials_dir>"
        credential_error = (
            f"missing required credentials: {', '.join(missing_credentials)} "
            f"(expected credentials in {cred_path_hint})"
        )
    if "gcp" in required_credentials:
        bootstrap_error = gcp_bootstrap_guard_message(runtime_root=runtime_root, module_ref=module_ref)
        if bootstrap_error:
            return _fail(ev, result, bootstrap_error)

    dep_error = prepare_ansible_controller_env(env=env, runtime_root=runtime_root, ansible_bin=ansible_bin)
    if dep_error:
        return _fail(ev, result, dep_error)

    configure_ansible_search_paths(
        env=env,
        runtime_root=runtime_root,
        module_id=module_id,
        ev=ev,
        result=result,
    )
    collections_error = ensure_hybridops_collections_available(env)
    if collections_error:
        return _fail(ev, result, collections_error)

    inputs = request.get("inputs")
    if not isinstance(inputs, dict):
        inputs = {}

    proxy_jump_auto_note = apply_proxy_jump_auto(inputs, runtime_root)
    if proxy_jump_auto_note:
        result.setdefault("warnings", []).append(proxy_jump_auto_note)

    # Preflight runs ahead of the real lifecycle command; respect the requested lifecycle.
    effective_lifecycle = command_name
    if command_name == "preflight":
        lc = str(request.get("lifecycle_command") or "").strip().lower()
        if lc:
            effective_lifecycle = lc

    required_env_key = "required_env_destroy" if effective_lifecycle == "destroy" else "required_env"
    required_env, required_env_error = resolve_required_env(inputs, key=required_env_key)
    if required_env_error:
        return _fail(ev, result, required_env_error)

    load_vault_env = as_bool(inputs.get("load_vault_env"), default=False)
    missing_before_vault = missing_env(env, required_env)

    vault_loaded: dict[str, str] = {}
    vault_error = ""
    if load_vault_env or missing_before_vault:
        vault_loaded, vault_error = merge_vault_env(env, runtime_root)

    missing_after_vault = missing_env(env, required_env)

    try:
        workdir.mkdir(parents=True, exist_ok=True)
    except Exception as exc:
        return _fail(ev, result, f"workdir setup failed: {exc}")

    materialized_ssh_key = ""
    try:
        materialized_ssh_key = materialize_ssh_private_key_from_env(
            inputs=inputs,
            env=env,
            workdir=workdir,
        )
    except Exception as exc:
        return _fail(ev, result, f"failed to materialize ssh_private_key_env: {exc}")

    inventory_path = workdir / ansible_cfg["inventory_file"]
    inventory_error = write_inventory(inventory_path, inputs)
    if inventory_error:
        return _fail(ev, result, inventory_error)

    outputs_path = workdir / "hyops.outputs.json"
    short_circuit_result = _maybe_short_circuit_destroy_for_absent_inventory(
        ev=ev,
        result=result,
        runtime_root=runtime_root,
        workdir=workdir,
        outputs_path=outputs_path,
        module_ref=module_ref,
        command_name=command_name,
        inputs=inputs,
    )
    if short_circuit_result is not None:
        return short_circuit_result

    extra_vars = dict(inputs)
    # Avoid clobbering Ansible reserved keywords (these are configured via inventory vars).
    extra_vars.pop("become", None)
    extra_vars.pop("become_user", None)
    extra_vars["hyops_lifecycle_command"] = command_name
    extra_vars["hyops_outputs_file"] = str(outputs_path)
    extra_vars["hyops_runtime_root"] = str(runtime_root)
    extra_vars["hyops_run_id"] = run_id
    extra_vars["hyops_module_ref"] = module_ref

    extra_vars_path = workdir / "hyops.inputs.yml"
    try:
        extra_vars_path.write_text(yaml.safe_dump(extra_vars, sort_keys=True), encoding="utf-8")
    except Exception as exc:
        return _fail(ev, result, f"failed to write runtime inputs: {exc}")

    playbook_file, playbook_note, playbook_error = resolve_playbook_file(
        command_name=command_name,
        ansible_cfg=ansible_cfg,
        inputs=inputs,
        runtime_root=runtime_root,
        module_id=module_id,
        pack_stack=pack_stack,
    )
    if playbook_note:
        result.setdefault("warnings", []).append(playbook_note)

    meta = {
        "command": command_name,
        "driver": driver_ref,
        "profile": profile_ref,
        "profile_path": profile_path,
        "pack_id": pack_id,
        "pack_stack": str(pack_stack),
        "playbook": {
            "file": playbook_file,
            "requested_apply_mode": str(inputs.get("apply_mode") or ""),
            "note": playbook_note,
        },
        "workdir": str(workdir),
        "inventory": str(inventory_path),
        "inputs_file": str(extra_vars_path),
        "outputs_file": str(outputs_path),
        "required_credentials": required_credentials,
        "available_credentials": available_credentials,
        "required_env": required_env,
        "vault": {
            "file": str((runtime_root / 'vault' / 'bootstrap.vault.env').resolve()),
            "loaded": bool(vault_loaded),
            "loaded_key_count": len(vault_loaded),
            "error": vault_error,
        },
        "ansible_env": {
            "ANSIBLE_ROLES_PATH": str(env.get("ANSIBLE_ROLES_PATH") or ""),
            "ANSIBLE_COLLECTIONS_PATH": str(env.get("ANSIBLE_COLLECTIONS_PATH") or ""),
            "ANSIBLE_COLLECTIONS_PATHS": str(env.get("ANSIBLE_COLLECTIONS_PATHS") or ""),
            "ANSIBLE_HOST_KEY_CHECKING": str(env.get("ANSIBLE_HOST_KEY_CHECKING") or ""),
            "ANSIBLE_LOCAL_TEMP": str(env.get("ANSIBLE_LOCAL_TEMP") or ""),
        },
        "proxy_jump": {
            "host": str(inputs.get("ssh_proxy_jump_host") or ""),
            "user": str(inputs.get("ssh_proxy_jump_user") or ""),
            "port": as_int(inputs.get("ssh_proxy_jump_port"), default=22),
            "auto_enabled": as_bool(inputs.get("ssh_proxy_jump_auto"), default=False),
            "auto_note": proxy_jump_auto_note,
        },
        "ssh_key": {
            "file": str(inputs.get("ssh_private_key_file") or ""),
            "env": str(inputs.get("ssh_private_key_env") or ""),
            "materialized_from_env": bool(materialized_ssh_key),
        },
    }
    ev.write_json("meta.json", meta)

    if credential_error:
        return _fail(ev, result, credential_error)

    if required_env and missing_after_vault:
        missing_list = sorted(missing_after_vault)
        missing = ", ".join(missing_list)
        env_hint = env_name or "<env>"
        vault_file = (runtime_root / "vault" / "bootstrap.vault.env").resolve()

        hint = f"missing required env vars: {missing}. "
        if vault_error:
            hint += f"{vault_error}. "
        hint += f"Provide them via shell env (VAR=value) or store them in runtime vault: {vault_file}. "
        hint += "Generate random defaults: "
        hint += f"hyops secrets ensure --env {env_hint} " + " ".join(missing_list) + ". "
        hint += "Or set explicit values: "
        hint += f"hyops secrets set --env {env_hint} KEY=VALUE ..."
        return _fail(ev, result, hint)

    if playbook_error:
        return _fail(ev, result, playbook_error)

    playbook_path = (pack_stack / playbook_file).resolve()
    if not playbook_path.exists():
        return _fail(ev, result, f"playbook not found: {playbook_path}")

    conn_ok, conn_err = connectivity_check(
        command_name=command_name,
        inputs=inputs,
        runtime_root=runtime_root,
        cwd=str(pack_stack),
        env=env,
        evidence_dir=evidence_dir,
        redact=redact,
    )
    if not conn_ok:
        return _fail(ev, result, f"{conn_err} (run record: {evidence_dir})")

    rke2_img_ok, rke2_img_err = rke2_image_preflight_check(
        command_name=command_name,
        module_ref=module_ref,
        inputs=inputs,
        cwd=str(pack_stack),
        env=env,
        evidence_dir=evidence_dir,
        redact=redact,
    )
    if not rke2_img_ok:
        return _fail(ev, result, f"{rke2_img_err} (run record: {evidence_dir})")

    if command_name == "preflight":
        result["status"] = "ok"
        result["normalized_outputs"] = {
            "preflight": {
                "module_ref": module_ref,
                "profile_ref": profile_ref,
                "pack_id": pack_id,
                "pack_stack": str(pack_stack),
                "required_credentials": required_credentials,
                "required_env": required_env,
            }
        }
        ev.write_json("driver_result.json", result)
        return result

    args, label, err_msg = resolve_execution_args(command_name, ansible_cfg)
    argv = build_playbook_argv(
        ansible_bin=ansible_bin,
        playbook_path=playbook_path,
        inventory_path=inventory_path,
        extra_vars_path=extra_vars_path,
        args=args,
    )

    run_result = run_capture_with_policy(
        argv=argv,
        cwd=str(pack_stack),
        env=env,
        evidence_dir=evidence_dir,
        label=label,
        timeout_s=timeout_s,
        redact=redact,
        retries=retries,
    )
    if run_result.rc != 0:
        hint = ansible_error_hint(
            command_name=command_name,
            module_ref=module_ref,
            inputs=inputs,
            evidence_dir=evidence_dir,
            label=label,
        )
        if hint:
            return _fail(ev, result, f"{err_msg}: {hint}")
        return _fail(ev, result, err_msg)

    outputs = load_outputs(outputs_path)

    result["status"] = "ok"
    result["normalized_outputs"] = {
        "published_outputs": outputs,
        "workdir": str(workdir),
        "command": command_name,
    }
    ev.write_json("driver_result.json", result)
    return result
