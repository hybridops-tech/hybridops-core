"""
purpose: State operations (unlock) routed through module drivers.
Architecture Decision: ADR-N/A (state command)
maintainer: HybridOps.Studio
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from hyops.drivers.registry import REGISTRY
from hyops.runtime.evidence import EvidenceWriter, init_evidence_dir, new_run_id
from hyops.runtime.layout import ensure_layout
from hyops.runtime.module_resolve import resolve_module
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
    q.add_argument("--inputs", default=None, help="Inputs YAML file.")
    q.add_argument("--lock-id", required=True, help="Lock ID to force-unlock.")
    q.add_argument(
        "--force",
        action="store_true",
        help="Required safety flag for unlock operations.",
    )
    q.add_argument("--out-dir", default=None, help="Override evidence root.")
    q.set_defaults(_handler=run_unlock)


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
        resolved = resolve_module(
            module_ref=getattr(ns, "module"),
            module_root=module_root,
            inputs_file=inputs_file,
            state_dir=paths.state_dir,
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
    print(f"evidence: {evidence_dir}")
    if status != "ok":
        err = str(result.get("error") or "").strip()
        if err:
            print(f"error: {err}", file=sys.stderr)
        return 1
    return 0


__all__ = ["add_state_subparser", "run_unlock"]
