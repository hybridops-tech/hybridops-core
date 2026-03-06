"""
Execution path for single-module apply/deploy/plan/validate/destroy/import.
"""

from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from hyops.commands._apply_helpers import (
    assert_safe_gcp_object_repo_slot,
    build_input_contract,
    driver_outputs,
    evidence_root,
    merge_template_image_outputs,
    normalize_published_outputs,
    persist_rerun_inputs,
    progress_log_hint,
    select_published_outputs,
)
from hyops.drivers.registry import REGISTRY
from hyops.runtime.evidence import EvidenceWriter, init_evidence_dir, new_run_id
from hyops.runtime.module_resolve import resolve_module
from hyops.runtime.module_state import write_module_state
from hyops.runtime.stamp import stamp_runtime


def run_single(
    *,
    paths,
    env_name: str | None,
    command_name: str,
    module_ref_raw: str,
    module_root: Path,
    inputs_file: Path | None,
    out_dir: str | None,
    skip_preflight: bool,
    state_instance: str | None,
    import_resource_address: str | None = None,
    import_resource_id: str | None = None,
) -> int:
    command_name = str(command_name or "apply").strip().lower()
    if command_name not in ("apply", "deploy", "plan", "validate", "destroy", "import"):
        command_name = "apply"

    run_label = "apply" if command_name == "deploy" else command_name
    run_id = new_run_id(run_label)

    try:
        resolved = resolve_module(
            module_ref_raw,
            module_root,
            inputs_file,
            state_dir=paths.state_dir,
            lifecycle_command=command_name,
        )
    except Exception as exc:
        print(f"ERR: {exc}", file=sys.stderr)
        return 1

    module_ref = resolved.module_ref

    driver_ref = str(resolved.execution.get("driver") or "").strip()
    profile_ref = str(resolved.execution.get("profile") or "").strip()
    pack_id = str(resolved.execution.get("pack_id") or "").strip()
    execution_hooks = resolved.execution.get("hooks") if isinstance(resolved.execution.get("hooks"), dict) else {}
    if not driver_ref or not profile_ref or not pack_id:
        raise SystemExit("ERR: spec.execution.driver/profile/pack_id are required")

    execution_payload = {
        "driver": driver_ref,
        "profile": profile_ref,
        "pack_id": pack_id,
        "hooks": execution_hooks,
    }

    try:
        raw_execution = resolved.spec.get("execution")
        raw_exec_for_validation: dict[str, Any] = (
            dict(raw_execution) if isinstance(raw_execution, dict) else {}
        )
        REGISTRY.validate_execution(driver_ref, raw_exec_for_validation)
    except Exception as exc:
        print(f"ERR: execution schema validation failed for {driver_ref}: {exc}", file=sys.stderr)
        return 1

    root = evidence_root(paths, out_dir, module_ref)
    evidence_dir = init_evidence_dir(root, run_id)
    ev = EvidenceWriter(evidence_dir)

    print(f"module={module_ref} status=running run_id={run_id}")
    print(f"evidence: {evidence_dir}")
    print(f"progress: logs={progress_log_hint(driver_ref, evidence_dir)}")

    try:
        stamp_runtime(
            paths.root,
            command=command_name,
            target=module_ref,
            run_id=run_id,
            evidence_dir=evidence_dir,
            extra={
                "module_ref_raw": module_ref_raw,
                "driver": driver_ref,
                "profile": profile_ref,
                "pack_id": pack_id,
                "required_credentials": resolved.required_credentials,
                "dependencies": resolved.dependencies,
                "dependency_warnings": resolved.dependency_warnings,
                "outputs_publish": resolved.outputs_publish,
                "module_root": str(module_root),
                "inputs_file": str(inputs_file) if inputs_file else "",
                "out_dir": str(out_dir or ""),
            },
        )
    except Exception:
        pass

    ev.write_json(
        "meta.json",
        {
            "command": command_name,
            "run_id": run_id,
            "module_ref": module_ref,
            "execution": execution_payload,
            "requirements": {"credentials": resolved.required_credentials},
            "dependencies": {
                "items": resolved.dependencies,
                "warnings": resolved.dependency_warnings,
            },
            "outputs": {"publish": resolved.outputs_publish},
            "paths": {
                "runtime_root": str(paths.root),
                "env": str(env_name or ""),
                "evidence_dir": str(evidence_dir),
                "state_dir": str(paths.state_dir),
            },
        },
    )

    try:
        assert_safe_gcp_object_repo_slot(
            paths.state_dir,
            module_ref,
            resolved.inputs,
            state_instance=state_instance,
        )
    except Exception as exc:
        ev.write_json("guard_failure.json", {"error": str(exc)})
        print(f"error: {exc}", file=sys.stderr)
        print(f"module={module_ref} status=error run_id={run_id}")
        print(f"evidence: {evidence_dir}")
        return 1

    try:
        driver_fn = REGISTRY.resolve(driver_ref)
    except Exception as exc:
        print(f"ERR: {exc}", file=sys.stderr)
        return 1

    request = {
        "command": command_name,
        "run_id": run_id,
        "module_ref": module_ref,
        "state_instance": state_instance or "",
        "module_dir": str(resolved.module_dir),
        "inputs": resolved.inputs,
        "execution": execution_payload,
        "requirements": {"credentials": resolved.required_credentials},
        "runtime": {
            "root": str(paths.root),
            "env": str(env_name or ""),
            "logs_dir": str(paths.logs_dir),
            "meta_dir": str(paths.meta_dir),
            "state_dir": str(paths.state_dir),
            "credentials_dir": str(paths.credentials_dir),
            "work_dir": str(paths.work_dir),
        },
        "evidence_dir": str(evidence_dir),
    }
    if command_name == "import":
        request["import"] = {
            "resource_address": str(import_resource_address or "").strip(),
            "resource_id": str(import_resource_id or "").strip(),
        }

    if not skip_preflight:
        print(f"progress: phase=preflight driver={driver_ref}")
        preflight_request = dict(request)
        preflight_request["command"] = "preflight"
        preflight_request["lifecycle_command"] = command_name
        preflight_result = driver_fn(preflight_request)
        ev.write_json("preflight_result.json", preflight_result)

        preflight_status = str(preflight_result.get("status", "unknown")).strip().lower()
        if preflight_status != "ok":
            preflight_error = str(preflight_result.get("error") or "").strip()
            if preflight_error:
                print(f"error: preflight failed: {preflight_error}", file=sys.stderr)
            else:
                print("error: preflight failed", file=sys.stderr)
            print(f"module={module_ref} status=error run_id={run_id}")
            print(f"evidence: {evidence_dir}")
            return 1

    print(f"progress: phase={command_name} driver={driver_ref}")
    result = driver_fn(request)
    ev.write_json("result.json", result)

    status = str(result.get("status", "unknown")).strip().lower()
    print(f"module={module_ref} status={status or 'unknown'} run_id={run_id}")
    print(f"evidence: {evidence_dir}")

    if status != "ok":
        err = str(result.get("error") or "").strip()
        if err:
            print(f"error: {err}", file=sys.stderr)
        return 1

    if command_name in ("apply", "deploy", "destroy", "import"):
        try:
            current_outputs = driver_outputs(result)
            published_outputs: dict[str, Any] = {}
            state_status = status
            rerun_inputs_file: Path | None = None
            if command_name in ("apply", "deploy", "import"):
                published_outputs = select_published_outputs(current_outputs, resolved.outputs_publish)
                published_outputs = merge_template_image_outputs(
                    paths.state_dir,
                    module_ref,
                    published_outputs,
                    state_instance=state_instance,
                )
                published_outputs = normalize_published_outputs(module_ref, published_outputs)
                if command_name in ("apply", "deploy"):
                    rerun_inputs_file = persist_rerun_inputs(
                        paths.config_dir,
                        module_ref,
                        resolved.inputs,
                        state_instance=state_instance,
                    )
            else:
                state_status = "destroyed"

            state_payload = {
                "module_ref": module_ref,
                "run_id": run_id,
                "status": state_status,
                "updated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                "execution": {
                    "driver": driver_ref,
                    "profile": profile_ref,
                    "pack_id": pack_id,
                },
                "requirements": {"credentials": resolved.required_credentials},
                "dependencies": resolved.dependencies,
                "outputs": published_outputs,
                "output_count": len(published_outputs),
                "evidence_dir": str(evidence_dir),
            }
            backend_binding = result.get("backend_binding")
            if isinstance(backend_binding, dict) and backend_binding:
                state_payload["execution"]["backend"] = dict(backend_binding)
            input_contract = build_input_contract(resolved.inputs)
            if input_contract:
                state_payload["input_contract"] = input_contract
            if state_instance:
                state_payload["state_instance"] = state_instance
            if rerun_inputs_file is not None:
                state_payload["rerun_inputs_file"] = str(rerun_inputs_file)

            state_path = write_module_state(
                paths.state_dir,
                module_ref,
                state_payload,
                state_instance=state_instance,
            )
            ev.write_json(
                "module_state.json",
                {
                    "path": str(state_path),
                    "published_outputs": sorted(list(published_outputs.keys())),
                    "publish_policy": resolved.outputs_publish,
                    "rerun_inputs_file": str(rerun_inputs_file) if rerun_inputs_file else "",
                },
            )
            if rerun_inputs_file is not None:
                print(f"rerun_inputs: {rerun_inputs_file}")
        except Exception as exc:
            print(f"ERR: failed to persist module state: {exc}", file=sys.stderr)
            return 1

    return 0
