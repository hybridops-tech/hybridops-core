"""
purpose: Run module execution lifecycle commands (apply/deploy/plan/validate/destroy/import).
Architecture Decision: ADR-N/A (module commands)
maintainer: HybridOps.Tech
"""

from __future__ import annotations

import argparse
import sys

from hyops.commands._apply_execute import run_single
from hyops.commands._apply_helpers import (
    dependency_inputs_file,
    dependency_order,
    module_state_ok,
)
from hyops.runtime.exitcodes import CANCELLED
from hyops.runtime.layout import ensure_layout
from hyops.runtime.module_state import normalize_state_instance
from hyops.runtime.paths import resolve_runtime_paths
from hyops.runtime.root import require_runtime_selection
from hyops.runtime.source_roots import resolve_input_path, resolve_module_root


def _configure_parser(p: argparse.ArgumentParser) -> None:
    p.add_argument("--root", default=None, help="Override runtime root.")
    p.add_argument("--env", default=None, help="Runtime environment namespace (e.g. dev, shared).")
    p.add_argument("--module", required=True, help="Module ref (e.g. core.gcp.project-factory or core/gcp/project-factory).")
    p.add_argument(
        "--module-root",
        default="modules",
        help="Module root directory (default: modules from cwd or HYOPS_CORE_ROOT).",
    )
    p.add_argument("--inputs", default=None, help="Inputs YAML file.")
    p.add_argument(
        "--with-deps",
        action="store_true",
        help="For apply/deploy, auto-apply required dependencies first based on spec.dependencies.",
    )
    p.add_argument(
        "--deps-inputs-dir",
        default=None,
        help="Optional directory of dependency input files (<module_id>.yml|.yaml or <module_ref>/inputs.yml).",
    )
    p.add_argument(
        "--deps-force",
        action="store_true",
        help="Apply dependencies even when their latest module state is already ok.",
    )
    p.add_argument("--out-dir", default=None, help="Override evidence root.")
    p.add_argument(
        "--state-instance",
        default=None,
        help="Optional state instance key for this module state slot (supports multi-instance module usage).",
    )
    p.add_argument(
        "--skip-preflight",
        action="store_true",
        help="Skip driver preflight checks (not recommended).",
    )
    p.set_defaults(_handler=run)


def add_subparser(sp: argparse._SubParsersAction) -> None:
    p_apply = sp.add_parser("apply", help="Apply a module spec using its selected driver.")
    _configure_parser(p_apply)

    p_deploy = sp.add_parser("deploy", help="Alias of apply.")
    _configure_parser(p_deploy)

    p_plan = sp.add_parser("plan", help="Plan a module spec using its selected driver.")
    _configure_parser(p_plan)

    p_validate = sp.add_parser("validate", help="Validate a module spec using its selected driver.")
    _configure_parser(p_validate)

    p_destroy = sp.add_parser("destroy", help="Destroy module resources using its selected driver.")
    _configure_parser(p_destroy)

    p_import = sp.add_parser("import", help="Import existing resource into module state using its selected driver.")
    _configure_parser(p_import)
    p_import.add_argument(
        "--resource-address",
        required=True,
        help="Resource address for import (e.g. module.x.resource_type.name).",
    )
    p_import.add_argument(
        "--resource-id",
        required=True,
        help="Provider resource ID to import.",
    )


def run(ns) -> int:
    env_name = str(getattr(ns, "env", "") or "").strip() or None
    try:
        require_runtime_selection(getattr(ns, "root", None), env_name, command_label=f"hyops {getattr(ns, 'cmd', 'apply')}")
        paths = resolve_runtime_paths(getattr(ns, "root", None), env_name)
    except Exception as exc:
        print(f"ERR: failed to resolve runtime layout: {exc}", file=sys.stderr)
        return 1
    ensure_layout(paths)

    command_name = str(getattr(ns, "cmd", "apply") or "apply").strip().lower()
    if command_name not in ("apply", "deploy", "plan", "validate", "destroy", "import"):
        command_name = "apply"

    module_ref_raw = str(getattr(ns, "module", "")).strip()
    module_root = resolve_module_root(getattr(ns, "module_root", "modules"))
    inputs_file = resolve_input_path(getattr(ns, "inputs", None))
    out_dir = getattr(ns, "out_dir", None)
    state_instance = normalize_state_instance(getattr(ns, "state_instance", None))

    with_deps = bool(getattr(ns, "with_deps", False))
    deps_force = bool(getattr(ns, "deps_force", False))
    deps_inputs_dir_arg = getattr(ns, "deps_inputs_dir", None)
    deps_inputs_dir = (
        resolve_input_path(str(deps_inputs_dir_arg))
        if deps_inputs_dir_arg
        else None
    )
    skip_preflight = bool(getattr(ns, "skip_preflight", False))
    allow_state_drift_recreate = bool(getattr(ns, "allow_state_drift_recreate", False))

    if with_deps and command_name not in ("apply", "deploy"):
        print("WARN: --with-deps is only applicable to apply/deploy; ignoring", file=sys.stderr)

    if with_deps and command_name in ("apply", "deploy"):
        try:
            dep_order = dependency_order(module_root, module_ref_raw)
        except Exception as e:
            print(f"ERR: dependency resolution failed: {e}", file=sys.stderr)
            return 1

        if dep_order:
            print(f"dependency_order: {', '.join(dep_order)}")

        for dep_ref in dep_order:
            if not deps_force and module_state_ok(paths.state_dir, dep_ref):
                print(f"dependency={dep_ref} status=skipped reason=state-ok")
                continue

            dep_inputs = dependency_inputs_file(dep_ref, deps_inputs_dir)
            if dep_inputs:
                print(f"dependency={dep_ref} status=apply inputs={dep_inputs}")
            else:
                print(f"dependency={dep_ref} status=apply")

            rc = run_single(
                paths=paths,
                env_name=env_name,
                command_name="apply",
                module_ref_raw=dep_ref,
                module_root=module_root,
                inputs_file=dep_inputs,
                out_dir=out_dir,
                skip_preflight=skip_preflight,
                state_instance=None,
                allow_state_drift_recreate=allow_state_drift_recreate,
            )
            if rc != 0:
                if rc == CANCELLED:
                    print(f"dependency={dep_ref} status=cancelled", file=sys.stderr)
                else:
                    print(f"ERR: dependency apply failed: {dep_ref}", file=sys.stderr)
                return rc

    if command_name == "import":
        resource_address = str(getattr(ns, "resource_address", "") or "").strip()
        resource_id = str(getattr(ns, "resource_id", "") or "").strip()
        if not resource_address:
            print("ERR: --resource-address is required for import", file=sys.stderr)
            return 2
        if not resource_id:
            print("ERR: --resource-id is required for import", file=sys.stderr)
            return 2

    rc = run_single(
        paths=paths,
        env_name=env_name,
        command_name=command_name,
        module_ref_raw=module_ref_raw,
        module_root=module_root,
        inputs_file=inputs_file,
        out_dir=out_dir,
        skip_preflight=skip_preflight,
        state_instance=state_instance,
        allow_state_drift_recreate=allow_state_drift_recreate,
        import_resource_address=str(getattr(ns, "resource_address", "") or "").strip(),
        import_resource_id=str(getattr(ns, "resource_id", "") or "").strip(),
    )
    return rc
