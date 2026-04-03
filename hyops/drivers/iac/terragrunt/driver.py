"""
purpose: Terragrunt driver (iac) for HybridOps.Core.
maintainer: HybridOps.Tech
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from hyops.drivers.iac.terragrunt.contracts import get_contract
from hyops.runtime.coerce import as_bool, as_int
from hyops.runtime.credentials import (
    apply_runtime_credential_env,
    available_credential_providers,
    provider_env_key,
)
from hyops.runtime.evidence import EvidenceWriter
from hyops.runtime.module_state import normalize_state_instance
from hyops.runtime.packs import PackResolved, resolve_pack_stack
from hyops.runtime.provider_bootstrap import gcp_bootstrap_guard_message

from ._internal.execution import (
    resolve_terragrunt_config as _resolve_terragrunt_config,
    run_terragrunt_init as _run_terragrunt_init,
    run_terragrunt_operation as _run_terragrunt_operation,
)
from ._internal.export_hooks import run_apply_export_hooks as _run_apply_export_hooks
from ._internal.meta import (
    write_driver_meta as _write_meta,
    write_runtime_inputs as _write_runtime_inputs,
)
from ._internal.policy import (
    check_credential_contracts as _check_credential_contracts,
    resolve_backend_mode as _resolve_backend_mode,
    resolve_credential_contracts as _resolve_credential_contracts,
    resolve_profile_policy as _resolve_profile_policy,
    resolve_required_credentials as _resolve_required_credentials,
)
from ._internal.post_apply_readiness import (
    run_post_apply_network_sdn_readiness as _run_post_apply_network_sdn_readiness,
    run_post_apply_ssh_readiness as _run_post_apply_ssh_readiness,
)
from ._internal.profile import (
    load_profile as _load_profile,
)
from ._internal.preflight import run_preflight_phase as _run_preflight_phase
from ._internal.runtime_env import build_runtime_env as _build_runtime_env
from ._internal.workspace import enforce_workspace_policy as _enforce_workspace_policy
from ._internal.workspace_binding import (
    allow_backend_binding_rehome as _allow_backend_binding_rehome,
    build_backend_binding as _build_backend_binding,
    check_backend_binding_drift as _check_backend_binding_drift,
)
from ._internal.stack_prepare import prepare_stack_workspace as _prepare_stack_workspace


def _fail(ev: EvidenceWriter, result: dict[str, Any], msg: str) -> dict[str, Any]:
    log_path = (ev.dir / "terragrunt.log").resolve()
    if log_path.exists() and "open:" not in str(msg):
        msg = f"{msg} (open: {log_path})"
    result["status"] = "error"
    result["error"] = msg
    ev.write_json("driver_result.json", result)
    return result


def run(request: dict[str, Any]) -> dict[str, Any]:
    evidence_dir = Path(str(request.get("evidence_dir") or "")).expanduser().resolve()
    evidence_dir.mkdir(parents=True, exist_ok=True)
    ev = EvidenceWriter(evidence_dir)
    tg_log = (evidence_dir / "terragrunt.log").resolve()

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
    lifecycle_command = str(request.get("lifecycle_command") or command_name).strip().lower()
    if command_name == "deploy":
        command_name = "apply"
    if command_name not in ("apply", "plan", "validate", "destroy", "import", "state_unlock", "preflight"):
        return _fail(ev, {"status": "error", "run_id": run_id, "normalized_outputs": {}, "warnings": []}, f"unsupported command for terragrunt driver: {command_name}")

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

    root_raw = str(runtime.get("root") or "").strip()
    if not root_raw:
        return _fail(ev, result, "missing runtime.root")

    runtime_root = Path(root_raw).expanduser().resolve()

    work_root_raw = str(runtime.get("work_dir") or "").strip()
    work_root = Path(work_root_raw).expanduser().resolve() if work_root_raw else (runtime_root / "work")

    raw_state_instance = request.get("state_instance")
    try:
        state_instance = normalize_state_instance(str(raw_state_instance or "").strip() or None) or ""
    except Exception as e:
        return _fail(ev, result, f"invalid state_instance: {e}")

    module_ref_identity = module_ref if not state_instance else f"{module_ref}#{state_instance}"
    module_id = module_ref_identity.replace("/", "__").replace("#", "__") if module_ref_identity else "unknown_module"
    contract = get_contract(module_ref)
    workdir = work_root / module_id / run_id
    stack_dst = workdir / "stack"

    env, env_name = _build_runtime_env(
        runtime_root=runtime_root,
        runtime=runtime if isinstance(runtime, dict) else {},
    )
    # Default to the shared runtime plugin cache from _build_runtime_env so
    # provider downloads remain stable across repeated runs. Operators can opt
    # into an isolated per-run cache when they need to troubleshoot provider
    # installation races in overlapping Terragrunt executions.
    isolate_plugin_cache = as_bool(
        env.get("HYOPS_TERRAFORM_ISOLATE_PLUGIN_CACHE")
        or runtime.get("terraform_isolate_plugin_cache"),
        default=False,
    )
    if isolate_plugin_cache and not str(os.environ.get("TF_PLUGIN_CACHE_DIR") or "").strip():
        run_plugin_cache = runtime_root / "cache" / "terraform" / "plugins-runs" / run_id
        try:
            run_plugin_cache.mkdir(parents=True, exist_ok=True)
            env["TF_PLUGIN_CACHE_DIR"] = str(run_plugin_cache)
        except Exception:
            # Keep the shared cache path chosen by _build_runtime_env on any mkdir failure.
            pass

    profile, profile_path_obj, profile_error = _load_profile(profile_ref)
    profile_path = str(profile_path_obj) if profile_path_obj else ""
    profile_policy, profile_policy_error = _resolve_profile_policy(profile)
    if profile_policy_error:
        return _fail(ev, result, f"profile policy validation failed: {profile_policy_error}")
    credential_contracts, credential_contracts_error = _resolve_credential_contracts(profile_policy)
    if credential_contracts_error:
        return _fail(ev, result, f"profile credential contract validation failed: {credential_contracts_error}")
    backend_mode, backend_mode_error = _resolve_backend_mode(profile_policy)
    if backend_mode_error:
        return _fail(ev, result, f"profile backend mode validation failed: {backend_mode_error}")

    backend_override = str(env.get("HYOPS_TERRAFORM_BACKEND_MODE") or "").strip().lower()
    if backend_override:
        if backend_override not in ("local", "cloud"):
            return _fail(
                ev,
                result,
                "HYOPS_TERRAFORM_BACKEND_MODE must be one of: local, cloud",
            )
        backend_mode = backend_override

    # Keep the env var normalized for templates.
    env["HYOPS_TERRAFORM_BACKEND_MODE"] = backend_mode

    if profile and str(profile.get("driver") or "").strip() not in ("", driver_ref):
        return _fail(ev, result, f"profile driver mismatch for {profile_ref}: expected {driver_ref}")

    policy_defaults = profile_policy.get("defaults") if isinstance(profile_policy, dict) else {}
    if not isinstance(policy_defaults, dict):
        policy_defaults = {}
    policy_timeout_raw = as_int(policy_defaults.get("command_timeout_s"), default=0)
    policy_timeout_s = int(policy_timeout_raw) if int(policy_timeout_raw) > 0 else None
    policy_retries = max(0, int(as_int(policy_defaults.get("retries"), default=0)))
    policy_redact = as_bool(policy_defaults.get("redact"), default=True)

    resolved: PackResolved | None = None
    pack_stack: Path | None = None
    pack_error = ""

    try:
        resolved = resolve_pack_stack(
            driver_ref=driver_ref,
            pack_id=pack_id,
            require_stack_files=("terragrunt.hcl",),
        )
        pack_stack = resolved.stack_dir
    except Exception as e:
        pack_error = str(e)

    required_credentials = _resolve_required_credentials(request)

    creds_raw = str(runtime.get("credentials_dir") or "").strip()
    credential_env = apply_runtime_credential_env(env, creds_raw if creds_raw else None)

    available_provider_keys = available_credential_providers(credential_env)
    available_credentials = sorted([p.lower() for p in available_provider_keys])

    missing_credentials: list[str] = []
    for provider in required_credentials:
        provider_key = provider_env_key(provider)
        if provider_key not in available_provider_keys:
            missing_credentials.append(provider)

    cred_path_hint = creds_raw if creds_raw else "<runtime.credentials_dir>"
    credential_error = (
        f"missing required credentials: {', '.join(missing_credentials)} (expected credentials in {cred_path_hint})"
        if missing_credentials
        else ""
    )
    credential_contract_error = _check_credential_contracts(
        required_credentials=required_credentials,
        credential_env=credential_env,
        contracts=credential_contracts,
        env=env,
    )
    if "gcp" in required_credentials:
        bootstrap_error = gcp_bootstrap_guard_message(runtime_root=runtime_root, module_ref=module_ref)
        if bootstrap_error:
            return _fail(ev, result, bootstrap_error)

    inputs = request.get("inputs")
    if not isinstance(inputs, dict):
        inputs = {}

    workspace_policy: dict[str, Any] | None = None
    workspace_error = ""
    export_infra_hook: dict[str, Any] | None = None
    export_infra_hook_error = ""
    workspace_name = ""
    backend_binding: dict[str, Any] = {}

    if pack_stack:
        workspace_policy, export_infra_hook, workspace_name, runtime_inputs_path, stack_prepare_error = _prepare_stack_workspace(
            pack_stack=pack_stack,
            workdir=workdir,
            stack_dst=stack_dst,
            runtime_root=runtime_root,
            env=env,
            profile=profile,
            credential_env=credential_env,
            profile_policy=profile_policy if isinstance(profile_policy, dict) else {},
            module_ref=module_ref,
            module_ref_identity=module_ref_identity,
            pack_id=pack_id,
            inputs=inputs,
            env_name=env_name,
            run_id=run_id,
            profile_ref=profile_ref,
            state_instance=state_instance,
            execution=execution if isinstance(execution, dict) else {},
            backend_mode=backend_mode,
        )
        if stack_prepare_error:
            return _fail(ev, result, stack_prepare_error)
        if runtime_inputs_path:
            ev.write_json("inputs_runtime.json", {"path": runtime_inputs_path})

    _write_meta(
        ev,
        command_name=command_name,
        driver_ref=driver_ref,
        profile_ref=profile_ref,
        pack_id=pack_id,
        module_ref=module_ref,
        runtime_root=runtime_root,
        workdir=workdir,
        stack_dst=stack_dst,
        env=env,
        evidence_dir=evidence_dir,
        resolved=resolved,
        pack_error=pack_error,
        profile_path=profile_path,
        profile_error=profile_error,
        profile_policy=profile_policy,
        credential_env=credential_env,
        required_credentials=required_credentials,
        available_credentials=available_credentials,
        credential_error=credential_error,
        credential_contract_error=credential_contract_error,
        workspace_policy=workspace_policy,
        workspace_error=workspace_error,
        export_infra_hook=export_infra_hook,
        export_infra_hook_error=export_infra_hook_error,
    )

    backend_binding = _build_backend_binding(
        backend_mode=backend_mode,
        workspace_policy=workspace_policy,
    )
    result["backend_binding"] = dict(backend_binding)
    ev.write_json("backend_binding.json", backend_binding)

    allow_backend_binding_drift = as_bool(env.get("HYOPS_ALLOW_BACKEND_BINDING_DRIFT"), default=False)
    if not allow_backend_binding_drift:
        rehome_allowed, rehome_reason = _allow_backend_binding_rehome(
            state_root=runtime_root / "state",
            module_ref=module_ref,
            state_instance=state_instance or None,
            inputs=inputs,
        )
        if rehome_allowed:
            allow_backend_binding_drift = True
            if rehome_reason:
                result["warnings"].append(rehome_reason)
    binding_error, binding_warning = _check_backend_binding_drift(
        state_root=runtime_root / "state",
        module_ref=module_ref,
        state_instance=state_instance or None,
        current_binding=backend_binding,
        allow_drift=allow_backend_binding_drift,
    )
    if binding_error:
        return _fail(ev, result, binding_error)
    if binding_warning:
        result["warnings"].append(binding_warning)

    if not pack_stack:
        return _fail(
            ev,
            result,
            f"pack resolution failed: {pack_error} (set HYOPS_PACKS_ROOT to the directory containing 'packs/')",
        )

    if credential_error:
        return _fail(ev, result, credential_error)
    if credential_contract_error:
        return _fail(ev, result, credential_contract_error)

    runtime_for_contract = dict(runtime) if isinstance(runtime, dict) else {}
    runtime_for_contract["state_instance"] = state_instance
    runtime_for_contract["lifecycle_command"] = lifecycle_command

    processed_inputs, contract_warnings, contract_error = contract.preprocess_inputs(
        command_name=command_name,
        module_ref=module_ref,
        inputs=dict(inputs),
        profile_policy=profile_policy,
        runtime=runtime_for_contract,
        env=env,
        credential_env=credential_env,
    )
    if contract_error:
        return _fail(ev, result, contract_error)
    if contract_warnings:
        result["warnings"].extend(contract_warnings)

    if processed_inputs != inputs:
        inputs = dict(processed_inputs)
        if stack_dst:
            try:
                runtime_inputs_path = _write_runtime_inputs(stack_dst, inputs)
                ev.write_json("inputs_runtime.json", {"path": str(runtime_inputs_path)})
            except Exception as exc:
                return _fail(ev, result, f"failed to rewrite runtime context after contract preprocessing: {exc}")

    preflight_handled, preflight_error = _run_preflight_phase(
        command_name=command_name,
        result=result,
        policy_defaults=policy_defaults,
        runtime_root=runtime_root,
        backend_mode=backend_mode,
        env=env,
        env_name=env_name,
        export_infra_hook=export_infra_hook,
        contract=contract,
        module_ref=module_ref,
        runtime=runtime_for_contract,
        profile_ref=profile_ref,
        pack_id=pack_id,
        required_credentials=required_credentials,
        inputs=inputs,
    )
    if preflight_handled:
        if preflight_error:
            return _fail(ev, result, preflight_error)
        ev.write_json("driver_result.json", result)
        return result

    terragrunt_cfg = _resolve_terragrunt_config(profile)

    init_error = _run_terragrunt_init(
        tg_bin=str(terragrunt_cfg["tg_bin"]),
        init_args=list(terragrunt_cfg["init_args"]),
        stack_dst=stack_dst,
        env=env,
        evidence_dir=evidence_dir,
        policy_timeout_s=policy_timeout_s,
        policy_redact=policy_redact,
        policy_retries=policy_retries,
        tg_log=tg_log,
    )
    if init_error:
        return _fail(ev, result, init_error)

    workspace_result, workspace_error, workspace_warning = _enforce_workspace_policy(
        backend_mode=backend_mode,
        workspace_policy=workspace_policy,
        env=env,
    )
    if workspace_result:
        ev.write_json("workspace_policy.json", workspace_result)
    if workspace_error:
        return _fail(ev, result, workspace_error)
    if workspace_warning:
        result["warnings"].append(workspace_warning)

    op_request = dict(request) if isinstance(request, dict) else {}
    if command_name == "state_unlock" and backend_mode == "cloud" and workspace_name:
        state_payload = op_request.get("state")
        if isinstance(state_payload, dict):
            state_payload = dict(state_payload)
            requested_lock_id = str(state_payload.get("lock_id") or "").strip()
            workspace_org = ""
            if isinstance(workspace_policy, dict):
                workspace_org = str(workspace_policy.get("org") or "").strip()
                if not workspace_org:
                    tfc = workspace_policy.get("terraform_cloud")
                    if isinstance(tfc, dict):
                        workspace_org = str(tfc.get("org") or "").strip()
            effective_lock_id = (
                f"{workspace_org}/{workspace_name}" if workspace_org else workspace_name
            )
            state_payload["requested_lock_id"] = requested_lock_id
            state_payload["lock_id"] = effective_lock_id
            op_request["state"] = state_payload

    outputs, op_error = _run_terragrunt_operation(
        command_name=command_name,
        request=op_request,
        tg_bin=str(terragrunt_cfg["tg_bin"]),
        apply_args=list(terragrunt_cfg["apply_args"]),
        destroy_args=list(terragrunt_cfg["destroy_args"]),
        import_args=list(terragrunt_cfg["import_args"]),
        force_unlock_args=list(terragrunt_cfg["force_unlock_args"]),
        plan_args=list(terragrunt_cfg["plan_args"]),
        validate_args=list(terragrunt_cfg["validate_args"]),
        output_args=list(terragrunt_cfg["output_args"]),
        stack_dst=stack_dst,
        env=env,
        evidence_dir=evidence_dir,
        policy_timeout_s=policy_timeout_s,
        policy_redact=policy_redact,
        policy_retries=policy_retries,
        tg_log=tg_log,
    )
    if op_error:
        return _fail(ev, result, op_error)

    post_apply_readiness_summary: dict[str, Any] | None = None
    readiness_warnings: list[str] = []
    readiness_error = ""
    post_apply_network_sdn_summary: dict[str, Any] | None = None
    network_sdn_warnings: list[str] = []
    network_sdn_error = ""
    if isinstance(outputs, dict):
        post_apply_readiness_summary, readiness_warnings, readiness_error = _run_post_apply_ssh_readiness(
            module_ref=module_ref,
            command_name=command_name,
            inputs=inputs,
            outputs=outputs,
            runtime_root=runtime_root,
            cwd=str(stack_dst),
            env=env,
            evidence_dir=evidence_dir,
            redact=policy_redact,
        )
        post_apply_network_sdn_summary, network_sdn_warnings, network_sdn_error = _run_post_apply_network_sdn_readiness(
            module_ref=module_ref,
            command_name=command_name,
            inputs=inputs,
            outputs=outputs,
            runtime_root=runtime_root,
            cwd=str(stack_dst),
            env=env,
            evidence_dir=evidence_dir,
            redact=policy_redact,
        )
    if post_apply_readiness_summary is not None:
        ev.write_json("post_apply_ssh_readiness.json", post_apply_readiness_summary)
    if post_apply_network_sdn_summary is not None:
        ev.write_json("post_apply_network_sdn_readiness.json", post_apply_network_sdn_summary)
    if readiness_warnings:
        result["warnings"].extend(list(readiness_warnings))
    if network_sdn_warnings:
        result["warnings"].extend(list(network_sdn_warnings))
    if readiness_error:
        return _fail(
            ev,
            result,
            f"post-apply SSH readiness failed: {readiness_error} (see post_apply_ssh_readiness.json and connectivity_* evidence)",
        )
    if network_sdn_error:
        return _fail(
            ev,
            result,
            "post-apply SDN readiness failed: "
            + str(network_sdn_error)
            + " (see post_apply_network_sdn_readiness.json and sdn_* evidence)",
        )

    hook_error = _run_apply_export_hooks(
        ev=ev,
        command_name=command_name,
        export_infra_hook=export_infra_hook,
        stack_dst=stack_dst,
        env=env,
        evidence_dir=evidence_dir,
        policy_timeout_s=policy_timeout_s,
        policy_redact=policy_redact,
        policy_retries=policy_retries,
        tg_log=tg_log,
        contract=contract,
        module_ref=module_ref,
        state_instance=state_instance,
        runtime=runtime if isinstance(runtime, dict) else {},
        runtime_root=runtime_root,
        env_name=env_name,
        result=result,
    )
    if hook_error:
        return _fail(ev, result, hook_error)

    result["status"] = "ok"
    result["normalized_outputs"] = {
        "terragrunt_outputs": outputs,
        "workdir": str(workdir),
        "command": command_name,
    }
    if post_apply_readiness_summary is not None:
        result["normalized_outputs"]["post_apply_ssh_readiness"] = post_apply_readiness_summary
    if post_apply_network_sdn_summary is not None:
        result["normalized_outputs"]["post_apply_network_sdn_readiness"] = post_apply_network_sdn_summary

    ev.write_json("driver_result.json", result)
    return result
