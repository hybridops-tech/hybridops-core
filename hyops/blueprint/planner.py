"""Blueprint planning and preflight helpers."""

from __future__ import annotations

import argparse
import os
from typing import Any

from hyops.drivers.iac.terragrunt.contracts import get_contract
from hyops.runtime.module_resolve import resolve_module
from hyops.runtime.source_roots import resolve_module_root
from hyops.preflight.command import run_module_driver_preflight

from .contracts import (
    enforce_step_contracts,
    explicit_step_inputs_changed,
    module_state_ok,
    resolved_step_inputs_file,
    step_state_ref,
)


def run_step_module_command(step: dict[str, Any], payload: dict[str, Any], ns, paths) -> int:
    from hyops.commands import apply as module_command

    inputs_file = resolved_step_inputs_file(step, payload, paths)
    step_ns = argparse.Namespace(
        cmd=step["action"],
        root=getattr(ns, "root", None),
        env=getattr(ns, "env", None),
        module=step["module_ref"],
        module_root=getattr(ns, "module_root", "modules"),
        inputs=str(inputs_file) if inputs_file else None,
        with_deps=bool(step.get("with_deps", False)),
        deps_inputs_dir=getattr(ns, "deps_inputs_dir", None),
        deps_force=bool(getattr(ns, "deps_force", False)),
        out_dir=getattr(ns, "out_dir", None),
        state_instance=str(step.get("state_instance") or "").strip() or None,
        allow_state_drift_recreate=bool(step.get("verify_state_on_skip", False)),
    )
    return int(module_command.run(step_ns))


def preflight_step(
    step: dict[str, Any],
    payload: dict[str, Any],
    ns,
    paths,
    *,
    assumed_state_ok: set[str] | None = None,
    deferred_driver_preflight_refs: set[str] | None = None,
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "id": step["id"],
        "module_ref": step["module_ref"],
        "module_state_ref": step_state_ref(step),
        "action": step["action"],
        "phase": step["phase"],
        "optional": bool(step.get("optional", False)),
        "checks": [],
        "status": "ready",
    }

    # Always materialize inline inputs to a deterministic file so operators can
    # reuse them for manual destroy/re-apply flows, even when the step is skipped.
    try:
        inputs_file = resolved_step_inputs_file(step, payload, paths)
        if inputs_file:
            result["inputs_file"] = str(inputs_file)
        result["checks"].append({"name": "inputs_file", "ok": True, "detail": str(inputs_file or "")})
    except Exception as exc:
        result["status"] = "blocked"
        result["checks"].append({"name": "inputs_file", "ok": False, "detail": str(exc)})
        return result

    if (
        bool(step.get("skip_if_state_ok", False))
        and step["action"] in ("apply", "deploy")
        and module_state_ok(paths.state_dir, step_state_ref(step))
    ):
        inputs_changed, inputs_detail = explicit_step_inputs_changed(step, payload, paths)
        if inputs_changed:
            result["checks"].append(
                {
                    "name": "state_skip",
                    "ok": True,
                    "detail": (
                        "existing state will not be skipped because explicit step inputs changed"
                        + (f": {inputs_detail}" if inputs_detail else "")
                    ),
                }
            )
        else:
            verify_state_on_skip = bool(step.get("verify_state_on_skip", False))
            if not verify_state_on_skip:
                result["status"] = "skipped"
                result["checks"].append(
                    {
                        "name": "state_skip",
                        "ok": True,
                        "detail": "skip_if_state_ok=true and module state is ok",
                    }
                )
                return result

            skip_status = "safe"
            skip_detail = ""
            try:
                contract = get_contract(step["module_ref"])
                skip_status, skip_detail = contract.evaluate_state_skip(
                    command_name="preflight",
                    module_ref=step["module_ref"],
                    state_root=paths.state_dir,
                    state_instance=str(step.get("state_instance") or "").strip() or None,
                    credentials_dir=paths.credentials_dir,
                    runtime_root=paths.root,
                    env={str(k): str(v) for k, v in os.environ.items()},
                )
            except Exception as exc:
                skip_status = "error"
                skip_detail = f"state skip verification failed: {exc}"

            if skip_status == "safe":
                result["status"] = "skipped"
                result["checks"].append(
                    {
                        "name": "state_skip",
                        "ok": True,
                        "detail": (
                            "skip_if_state_ok=true and live state verification passed"
                            + (f": {skip_detail}" if skip_detail else "")
                        ),
                    }
                )
                return result

            if skip_status == "error":
                result["status"] = "blocked"
                result["checks"].append(
                    {
                        "name": "state_skip",
                        "ok": False,
                        "detail": skip_detail or "live state verification failed",
                    }
                )
                return result

            result["checks"].append(
                {
                    "name": "state_skip",
                    "ok": True,
                    "detail": (
                        "existing state will not be skipped because live verification detected drift"
                        + (f": {skip_detail}" if skip_detail else "")
                    ),
                }
            )

    try:
        enforce_step_contracts(step, payload, paths, assumed_state_ok=assumed_state_ok)
        result["checks"].append({"name": "contracts", "ok": True, "detail": "ok"})
    except Exception as exc:
        result["status"] = "blocked"
        result["checks"].append({"name": "contracts", "ok": False, "detail": str(exc)})
        return result

    try:
        module_root = resolve_module_root(getattr(ns, "module_root", "modules"))
        resolved = resolve_module(
            step["module_ref"],
            module_root,
            inputs_file,
            state_dir=paths.state_dir,
            runtime_root=paths.root,
            invocation_command="preflight",
            assumed_state_ok=assumed_state_ok,
        )
        result["checks"].append({"name": "module_resolve", "ok": True, "detail": "ok"})
        result["required_credentials"] = list(resolved.required_credentials)
        result["outputs_publish"] = list(resolved.outputs_publish)
    except Exception as exc:
        result["status"] = "blocked"
        result["checks"].append({"name": "module_resolve", "ok": False, "detail": str(exc)})
        return result

    if deferred_driver_preflight_refs:
        refs = ", ".join(sorted(deferred_driver_preflight_refs))
        result["checks"].append(
            {
                "name": "module_preflight",
                "ok": True,
                "detail": f"deferred until upstream blueprint state exists: {refs}",
            }
        )
        result["driver_preflight"] = {
            "status": "deferred",
            "deferred_state_refs": sorted(deferred_driver_preflight_refs),
        }
        return result

    try:
        driver_preflight = run_module_driver_preflight(
            paths=paths,
            env_name=getattr(ns, "env", None),
            module_ref=step["module_ref"],
            module_root=module_root,
            inputs_file=inputs_file,
            lifecycle_command=str(step["action"] or "").strip().lower() or None,
            state_instance=str(step.get("state_instance") or "").strip() or None,
            assumed_state_ok=assumed_state_ok,
            allow_state_drift_recreate=(
                bool(step.get("verify_state_on_skip", False))
                and any(check.get("name") == "state_skip" for check in result["checks"])
            ),
        )
        result["driver_preflight"] = driver_preflight
        driver_status = str(driver_preflight.get("status") or "").strip().lower()
        if driver_status != "ok":
            result["status"] = "blocked"
            detail = str(driver_preflight.get("error") or f"status={driver_status}")
            result["checks"].append({"name": "module_preflight", "ok": False, "detail": detail})
            return result
        result["checks"].append({"name": "module_preflight", "ok": True, "detail": "ok"})
    except Exception as exc:
        result["status"] = "blocked"
        result["checks"].append({"name": "module_preflight", "ok": False, "detail": str(exc)})

    return result


def compute_preflight(
    payload: dict[str, Any],
    ns,
    paths,
) -> tuple[list[dict[str, Any]], list[str], list[str]]:
    by_id = {step["id"]: step for step in payload["steps"]}
    required_failures: list[str] = []
    optional_failures: list[str] = []
    step_results: list[dict[str, Any]] = []

    # Track only states planned by preceding blueprint steps in this run.
    # Existing on-disk states are resolved normally so preflight keeps real
    # safety checks for non-blueprint dependencies.
    assumed_state_ok: set[str] = set()

    for step_id in payload["order"]:
        step = by_id[step_id]
        deferred_driver_preflight_refs: set[str] = set()
        raw_deps = step.get("requires")
        if raw_deps is None:
            raw_deps = step.get("depends_on", [])
        for dep_id in raw_deps or []:
            dep_step = by_id.get(str(dep_id))
            if not isinstance(dep_step, dict):
                continue
            dep_state_ref = step_state_ref(dep_step)
            if dep_state_ref in assumed_state_ok and not module_state_ok(paths.state_dir, dep_state_ref):
                deferred_driver_preflight_refs.add(dep_state_ref)
        result = preflight_step(
            step,
            payload,
            ns,
            paths,
            assumed_state_ok=assumed_state_ok,
            deferred_driver_preflight_refs=deferred_driver_preflight_refs,
        )
        step_results.append(result)

        if result["status"] == "blocked":
            if result.get("optional", False):
                optional_failures.append(step_id)
            else:
                required_failures.append(step_id)
            continue

        if (
            not result.get("optional", False)
            and step["action"] in ("apply", "deploy")
            and result["status"] in ("ready", "skipped")
        ):
            assumed_state_ok.add(step_state_ref(step))

    return step_results, required_failures, optional_failures
