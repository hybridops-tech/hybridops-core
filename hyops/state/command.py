"""
purpose: State operations (unlock) routed through module drivers.
maintainer: HybridOps.Tech
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from hyops.drivers.registry import REGISTRY
from hyops.runtime.evidence import EvidenceWriter, init_evidence_dir, new_run_id
from hyops.runtime.layout import ensure_layout
from hyops.runtime.module_resolve import resolve_module
from hyops.runtime.module_state import (
    normalize_state_instance,
    read_module_state,
    write_module_state,
)
from hyops.runtime.paths import resolve_runtime_paths
from hyops.runtime.refs import module_id_from_ref
from hyops.runtime.source_roots import resolve_input_path, resolve_module_root


def add_state_subparser(sp: argparse._SubParsersAction) -> None:
    p = sp.add_parser("state", help="State helper commands.")
    ssp = p.add_subparsers(dest="state_cmd", required=True)

    q = ssp.add_parser("unlock", help="Force unlock module state lock through selected driver.")
    q.add_argument("--root", default=None, help="Override runtime root.")
    q.add_argument("--env", default=None, help="Runtime environment namespace (e.g. dev, shared).")
    q.add_argument(
        "--module",
        required=True,
        help="Module ref (e.g. core.gcp.project-factory or core/gcp/project-factory).",
    )
    q.add_argument(
        "--module-root",
        default="modules",
        help="Module root directory (default: modules from cwd or HYOPS_CORE_ROOT).",
    )
    q.add_argument(
        "--state-instance",
        default=None,
        help="Optional module state instance (same value used with hyops apply --state-instance).",
    )
    q.add_argument("--inputs", default=None, help="Inputs YAML file.")
    q.add_argument("--lock-id", required=True, help="Lock ID to force-unlock.")
    q.add_argument(
        "--force",
        action="store_true",
        help="Required safety flag for unlock operations.",
    )
    q.add_argument("--out-dir", default=None, help="Override evidence root.")
    q.set_defaults(_handler=run_unlock)

    d = ssp.add_parser(
        "detach",
        help="Detach one resource from IaC state without changing the provider resource.",
    )
    d.add_argument("--root", default=None, help="Override runtime root.")
    d.add_argument("--env", default=None, help="Runtime environment namespace (e.g. dev, shared).")
    d.add_argument(
        "--module",
        required=True,
        help="Module ref (e.g. core.gcp.project-factory or core/gcp/project-factory).",
    )
    d.add_argument(
        "--module-root",
        default="modules",
        help="Module root directory (default: modules from cwd or HYOPS_CORE_ROOT).",
    )
    d.add_argument(
        "--state-instance",
        default=None,
        help="Optional module state instance (same value used with hyops apply --state-instance).",
    )
    d.add_argument("--inputs", default=None, help="Inputs YAML file.")
    d.add_argument(
        "--resource-address",
        required=True,
        help="Exact Terraform resource address to detach.",
    )
    d.add_argument(
        "--expected-resource-id",
        required=True,
        help="Exact resource ID currently expected in Terraform state; prevents detaching the wrong resource.",
    )
    d.add_argument(
        "--force",
        action="store_true",
        help="Required safety flag. This operation changes IaC state only and never deletes the provider resource.",
    )
    d.add_argument("--out-dir", default=None, help="Override evidence root.")
    d.set_defaults(_handler=run_detach)


def run_unlock(ns) -> int:
    if not bool(getattr(ns, "force", False)):
        print("ERR: state unlock requires --force", file=sys.stderr)
        return 2

    lock_id = str(getattr(ns, "lock_id", "") or "").strip()
    if not lock_id:
        print("ERR: --lock-id is required", file=sys.stderr)
        return 2

    try:
        paths = resolve_runtime_paths(getattr(ns, "root", None), getattr(ns, "env", None))
        ensure_layout(paths)
    except Exception as exc:
        print(f"ERR: failed to resolve runtime layout: {exc}", file=sys.stderr)
        return 1

    module_root = resolve_module_root(str(getattr(ns, "module_root", "modules")))
    inputs_file = resolve_input_path(str(ns.inputs) if getattr(ns, "inputs", None) else None)
    try:
        state_instance = normalize_state_instance(
            str(getattr(ns, "state_instance", "") or "").strip() or None
        )
    except ValueError as exc:
        print(f"ERR: {exc}", file=sys.stderr)
        return 2

    try:
        resolved = resolve_module(
            module_ref=getattr(ns, "module"),
            module_root=module_root,
            inputs_file=inputs_file,
            state_dir=paths.state_dir,
            runtime_root=paths.root,
        )
    except Exception as exc:
        print(f"ERR: {exc}", file=sys.stderr)
        return 1

    module_ref = resolved.module_ref
    module_id = module_id_from_ref(module_ref) or "unknown_module"
    run_id = new_run_id("state-unlock")

    evidence_root = (
        Path(str(ns.out_dir)).expanduser().resolve() / "state" / module_id
        if getattr(ns, "out_dir", None)
        else paths.logs_dir / "state" / module_id
    )
    evidence_dir = init_evidence_dir(evidence_root, run_id)
    ev = EvidenceWriter(evidence_dir)

    driver_ref = str(resolved.execution.get("driver") or "").strip()
    profile_ref = str(resolved.execution.get("profile") or "").strip()
    pack_id = str(resolved.execution.get("pack_id") or "").strip()
    execution_hooks = (
        resolved.execution.get("hooks")
        if isinstance(resolved.execution.get("hooks"), dict)
        else {}
    )
    execution_payload = {
        "driver": driver_ref,
        "profile": profile_ref,
        "pack_id": pack_id,
        "hooks": execution_hooks,
    }

    try:
        driver_fn = REGISTRY.resolve(driver_ref)
    except Exception as exc:
        print(f"ERR: {exc}", file=sys.stderr)
        return 1

    request = {
        "command": "state_unlock",
        "run_id": run_id,
        "module_ref": module_ref,
        "state_instance": state_instance or "",
        "module_dir": str(resolved.module_dir),
        "inputs": resolved.inputs,
        "execution": execution_payload,
        "requirements": {"credentials": resolved.required_credentials},
        "state": {
            "lock_id": lock_id,
            "force": True,
        },
        "runtime": {
            "root": str(paths.root),
            "logs_dir": str(paths.logs_dir),
            "meta_dir": str(paths.meta_dir),
            "state_dir": str(paths.state_dir),
            "credentials_dir": str(paths.credentials_dir),
            "work_dir": str(paths.work_dir),
        },
        "evidence_dir": str(evidence_dir),
    }

    result = driver_fn(request)
    ev.write_json("result.json", result)

    status = str(result.get("status") or "unknown").strip().lower()
    print(f"module={module_ref} status={status or 'unknown'} run_id={run_id}")
    print(f"run record: {evidence_dir}")
    if status != "ok":
        err = str(result.get("error") or "").strip()
        if err:
            print(f"error: {err}", file=sys.stderr)
        return 1
    return 0


def run_detach(ns) -> int:
    """Detach a known resource from the selected IaC state slot.

    This is deliberately stricter than raw ``terraform state rm``: the operator
    must provide the exact resource address and the ID that HybridOps reads
    before removing it. The selected driver records both operations as evidence.
    """

    if not bool(getattr(ns, "force", False)):
        print("ERR: state detach requires --force", file=sys.stderr)
        return 2

    resource_address = str(getattr(ns, "resource_address", "") or "").strip()
    expected_resource_id = str(getattr(ns, "expected_resource_id", "") or "").strip()
    if not resource_address:
        print("ERR: --resource-address is required", file=sys.stderr)
        return 2
    if not expected_resource_id:
        print("ERR: --expected-resource-id is required", file=sys.stderr)
        return 2

    try:
        paths = resolve_runtime_paths(getattr(ns, "root", None), getattr(ns, "env", None))
        ensure_layout(paths)
    except Exception as exc:
        print(f"ERR: failed to resolve runtime layout: {exc}", file=sys.stderr)
        return 1

    module_root = resolve_module_root(str(getattr(ns, "module_root", "modules")))
    inputs_file = resolve_input_path(str(ns.inputs) if getattr(ns, "inputs", None) else None)
    try:
        state_instance = normalize_state_instance(
            str(getattr(ns, "state_instance", "") or "").strip() or None
        )
    except ValueError as exc:
        print(f"ERR: {exc}", file=sys.stderr)
        return 2

    try:
        resolved = resolve_module(
            module_ref=getattr(ns, "module"),
            module_root=module_root,
            inputs_file=inputs_file,
            state_dir=paths.state_dir,
            runtime_root=paths.root,
        )
    except Exception as exc:
        print(f"ERR: {exc}", file=sys.stderr)
        return 1

    module_ref = resolved.module_ref
    module_id = module_id_from_ref(module_ref) or "unknown_module"
    run_id = new_run_id("state-detach")
    evidence_root = (
        Path(str(ns.out_dir)).expanduser().resolve() / "state" / module_id
        if getattr(ns, "out_dir", None)
        else paths.logs_dir / "state" / module_id
    )
    evidence_dir = init_evidence_dir(evidence_root, run_id)
    ev = EvidenceWriter(evidence_dir)

    try:
        prior_state: dict[str, Any] = read_module_state(
            paths.state_dir,
            module_ref,
            state_instance=state_instance,
        )
    except Exception as exc:
        print(f"ERR: unable to read existing module state: {exc}", file=sys.stderr)
        return 1
    ev.write_json("prior_module_state.json", prior_state)

    driver_ref = str(resolved.execution.get("driver") or "").strip()
    profile_ref = str(resolved.execution.get("profile") or "").strip()
    pack_id = str(resolved.execution.get("pack_id") or "").strip()
    execution_hooks = (
        resolved.execution.get("hooks")
        if isinstance(resolved.execution.get("hooks"), dict)
        else {}
    )
    execution_payload = {
        "driver": driver_ref,
        "profile": profile_ref,
        "pack_id": pack_id,
        "hooks": execution_hooks,
    }

    try:
        driver_fn = REGISTRY.resolve(driver_ref)
    except Exception as exc:
        print(f"ERR: {exc}", file=sys.stderr)
        return 1

    request = {
        "command": "state_detach",
        "run_id": run_id,
        "module_ref": module_ref,
        "state_instance": state_instance or "",
        "module_dir": str(resolved.module_dir),
        "inputs": resolved.inputs,
        "execution": execution_payload,
        "requirements": {"credentials": resolved.required_credentials},
        "state": {
            "resource_address": resource_address,
            "expected_resource_id": expected_resource_id,
            "force": True,
        },
        "runtime": {
            "root": str(paths.root),
            "logs_dir": str(paths.logs_dir),
            "meta_dir": str(paths.meta_dir),
            "state_dir": str(paths.state_dir),
            "credentials_dir": str(paths.credentials_dir),
            "work_dir": str(paths.work_dir),
        },
        "evidence_dir": str(evidence_dir),
    }

    result = driver_fn(request)
    ev.write_json("result.json", result)
    status = str(result.get("status") or "unknown").strip().lower()
    print(f"module={module_ref} status={status or 'unknown'} run_id={run_id}")
    print(f"run record: {evidence_dir}")
    if status != "ok":
        err = str(result.get("error") or "").strip()
        if err:
            print(f"error: {err}", file=sys.stderr)
        return 1

    backend_binding = result.get("backend_binding")
    execution_state: dict[str, Any] = {
        "driver": driver_ref,
        "profile": profile_ref,
        "pack_id": pack_id,
    }
    if isinstance(backend_binding, dict) and backend_binding:
        execution_state["backend"] = dict(backend_binding)
    detach_summary = result.get("state_detach")
    state_payload: dict[str, Any] = {
        "module_ref": module_ref,
        "run_id": run_id,
        "status": "detached",
        "updated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "execution": execution_state,
        "requirements": {"credentials": resolved.required_credentials},
        "dependencies": resolved.dependencies,
        "outputs": {},
        "output_count": 0,
        "evidence_dir": str(evidence_dir),
        "detached_resources": [detach_summary] if isinstance(detach_summary, dict) else [],
    }
    if state_instance:
        state_payload["state_instance"] = state_instance
    state_path = write_module_state(
        paths.state_dir,
        module_ref,
        state_payload,
        state_instance=state_instance,
    )
    ev.write_json("module_state.json", {"path": str(state_path), "status": "detached"})
    return 0


__all__ = ["add_state_subparser", "run_detach", "run_unlock"]
