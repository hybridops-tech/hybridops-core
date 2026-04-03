"""
purpose: Rebuild module resources by running preflight, destroy, then apply.
maintainer: HybridOps.Tech
"""

from __future__ import annotations

import argparse
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from hyops.commands import apply as cmd_apply
from hyops.preflight import command as cmd_preflight
from hyops.runtime.evidence import EvidenceWriter, init_evidence_dir, new_run_id
from hyops.runtime.exitcodes import CANCELLED
from hyops.runtime.layout import ensure_layout
from hyops.runtime.paths import resolve_runtime_paths
from hyops.runtime.refs import module_id_from_ref, normalize_module_ref
from hyops.runtime.root import require_runtime_selection


def add_subparser(sp: argparse._SubParsersAction) -> None:
    p = sp.add_parser(
        "rebuild",
        help="Rebuild module resources (strict preflight -> destroy -> apply).",
    )
    p.add_argument("--root", default=None, help="Override runtime root.")
    p.add_argument("--env", default=None, help="Runtime environment namespace (e.g. dev, shared).")
    p.add_argument(
        "--module",
        required=True,
        help="Module ref (e.g. core.gcp.project-factory or core/gcp/project-factory).",
    )
    p.add_argument(
        "--module-root",
        default="modules",
        help="Module root directory (default: modules from cwd or HYOPS_CORE_ROOT).",
    )
    p.add_argument("--inputs", default=None, help="Inputs YAML file.")
    p.add_argument("--out-dir", default=None, help="Override evidence root.")
    p.add_argument(
        "--skip-preflight",
        action="store_true",
        help="Skip preflight phase (not recommended).",
    )
    p.add_argument(
        "--yes",
        action="store_true",
        help="Confirm destructive rebuild without interactive prompt.",
    )
    p.add_argument(
        "--confirm-module",
        default=None,
        help="Safety guard: must exactly match --module (canonical ref) to proceed.",
    )
    p.add_argument(
        "--with-deps",
        action="store_true",
        help="For apply phase, auto-apply required dependencies first based on spec.dependencies.",
    )
    p.add_argument(
        "--deps-inputs-dir",
        default=None,
        help="Optional directory of dependency input files (<module_id>.yml|.yaml or <module_ref>/inputs.yml).",
    )
    p.add_argument(
        "--deps-force",
        action="store_true",
        help="For apply phase, apply dependencies even when latest module state is already ok.",
    )
    p.set_defaults(_handler=run)


def _ask_confirmation(module_ref: str) -> bool | None:
    prompt = f"rebuild will destroy and re-apply module '{module_ref}'. continue? [y/N]: "
    try:
        answer = input(prompt)
    except EOFError:
        return False
    except KeyboardInterrupt:
        print()
        return None
    return str(answer or "").strip().lower() in ("y", "yes")


def _module_id(module_ref: str) -> str:
    ref = normalize_module_ref(module_ref)
    if not ref:
        return ""
    return module_id_from_ref(ref) or ""


def run(ns) -> int:
    module_ref_raw = str(getattr(ns, "module", "")).strip()
    module_ref = normalize_module_ref(module_ref_raw)
    if not module_ref:
        print("ERR: module_ref is required")
        return 2

    confirm_module_raw = str(getattr(ns, "confirm_module", "") or "").strip()
    if confirm_module_raw:
        confirm_module = normalize_module_ref(confirm_module_raw)
        if not confirm_module:
            print("ERR: --confirm-module is invalid")
            return 2
        if confirm_module != module_ref:
            print(
                "ERR: --confirm-module mismatch; expected "
                f"{module_ref!r} but got {confirm_module!r}"
            )
            return 2

    if not bool(getattr(ns, "yes", False)):
        confirmed = _ask_confirmation(module_ref)
        if confirmed is None:
            print("Cancelled by user.")
            return CANCELLED
        if not confirmed:
            print("Cancelled.")
            return 2

    try:
        require_runtime_selection(
            getattr(ns, "root", None),
            getattr(ns, "env", None),
            command_label="hyops rebuild",
        )
        paths = resolve_runtime_paths(getattr(ns, "root", None), getattr(ns, "env", None))
        ensure_layout(paths)
    except Exception as exc:
        print(f"ERR: failed to resolve runtime layout: {exc}")
        return 1

    module_id = _module_id(module_ref)
    if not module_id:
        print(f"ERR: invalid module_ref: {module_ref_raw}")
        return 2

    run_id = new_run_id("rebuild")
    out_dir_raw = getattr(ns, "out_dir", None)
    out_dir = str(out_dir_raw).strip() if out_dir_raw is not None else ""
    if out_dir:
        evidence_root = Path(out_dir).expanduser().resolve() / "rebuild" / module_id
    else:
        evidence_root = paths.logs_dir / "rebuild" / module_id
    evidence_dir = init_evidence_dir(evidence_root, run_id)
    ev = EvidenceWriter(evidence_dir)

    summary: dict[str, Any] = {
        "command": "rebuild",
        "run_id": run_id,
        "module_ref": module_ref,
        "module_id": module_id,
        "status": "error",
        "phases": {},
    }
    def _write_rebuild_metadata() -> None:
        ev.write_json("meta.json", summary)
        ev.write_json("rebuild_summary.json", summary)

    _write_rebuild_metadata()

    if not bool(getattr(ns, "skip_preflight", False)):
        preflight_ns = SimpleNamespace(
            root=getattr(ns, "root", None),
            env=getattr(ns, "env", None),
            target=None,
            json=False,
            strict=True,
            vault_file=None,
            vault_password_file=None,
            vault_password_command=None,
            module=module_ref,
            module_root=getattr(ns, "module_root", "modules"),
            inputs=getattr(ns, "inputs", None),
        )
        rc_preflight = int(cmd_preflight.run(preflight_ns))
        summary["phases"]["preflight"] = {"status": "ok" if rc_preflight == 0 else "error", "exit_code": rc_preflight}
        if rc_preflight == CANCELLED:
            summary["phases"]["preflight"]["status"] = "cancelled"
        _write_rebuild_metadata()
        if rc_preflight != 0:
            phase_status = "cancelled" if rc_preflight == CANCELLED else "error"
            print(f"rebuild phase=preflight status={phase_status} exit_code={rc_preflight}")
            print(f"run record: {evidence_dir}")
            return rc_preflight

    destroy_ns = SimpleNamespace(
        cmd="destroy",
        root=getattr(ns, "root", None),
        env=getattr(ns, "env", None),
        module=module_ref,
        module_root=getattr(ns, "module_root", "modules"),
        inputs=getattr(ns, "inputs", None),
        with_deps=False,
        deps_inputs_dir=None,
        deps_force=False,
        out_dir=getattr(ns, "out_dir", None),
        skip_preflight=bool(getattr(ns, "skip_preflight", False)),
    )
    rc_destroy = int(cmd_apply.run(destroy_ns))
    summary["phases"]["destroy"] = {"status": "ok" if rc_destroy == 0 else "error", "exit_code": rc_destroy}
    if rc_destroy == CANCELLED:
        summary["phases"]["destroy"]["status"] = "cancelled"
    _write_rebuild_metadata()
    if rc_destroy != 0:
        phase_status = "cancelled" if rc_destroy == CANCELLED else "error"
        print(f"rebuild phase=destroy status={phase_status} exit_code={rc_destroy}")
        print(f"run record: {evidence_dir}")
        return rc_destroy

    apply_ns = SimpleNamespace(
        cmd="apply",
        root=getattr(ns, "root", None),
        env=getattr(ns, "env", None),
        module=module_ref,
        module_root=getattr(ns, "module_root", "modules"),
        inputs=getattr(ns, "inputs", None),
        with_deps=bool(getattr(ns, "with_deps", False)),
        deps_inputs_dir=getattr(ns, "deps_inputs_dir", None),
        deps_force=bool(getattr(ns, "deps_force", False)),
        out_dir=getattr(ns, "out_dir", None),
        skip_preflight=bool(getattr(ns, "skip_preflight", False)),
    )
    rc_apply = int(cmd_apply.run(apply_ns))
    summary["phases"]["apply"] = {"status": "ok" if rc_apply == 0 else "error", "exit_code": rc_apply}
    if rc_apply == CANCELLED:
        summary["phases"]["apply"]["status"] = "cancelled"
    summary["status"] = "ok" if rc_apply == 0 else "error"
    if rc_apply == CANCELLED:
        summary["status"] = "cancelled"
    _write_rebuild_metadata()

    print(f"rebuild module={module_ref} status={summary['status']} run_id={run_id}")
    print(f"run record: {evidence_dir}")
    return rc_apply
