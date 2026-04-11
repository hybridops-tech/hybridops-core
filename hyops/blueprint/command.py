"""Blueprint CLI commands."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
from pathlib import Path
from typing import Any

from hyops.drivers.iac.terragrunt.contracts import get_contract
from hyops.runtime.exitcodes import CANCELLED, OPERATOR_ERROR
from hyops.runtime.layout import ensure_layout
from hyops.runtime.paths import resolve_runtime_paths
from hyops.runtime.root import require_runtime_selection
from hyops.runtime.source_roots import resolve_blueprints_root

from .contracts import (
    enforce_step_contracts,
    explicit_step_inputs_changed,
    module_state_ok,
    module_state_status,
    resolved_step_inputs_file,
    step_state_ref,
)
from .planner import compute_preflight, run_step_module_command
from .schema import load_blueprint, resolve_blueprint_file, validate_blueprint


def _resolve_and_validate(ns) -> dict[str, Any]:
    blueprints_root = resolve_blueprints_root(getattr(ns, "blueprints_root", "blueprints"))
    path = resolve_blueprint_file(
        ref=str(getattr(ns, "ref", "") or ""),
        file_path=str(getattr(ns, "file", "") or ""),
        blueprints_root=blueprints_root,
    )
    spec = load_blueprint(path)
    return validate_blueprint(spec, path)


def _enforce_runtime_blueprint_file_scope(ns, paths, *, command_label: str) -> None:
    explicit = str(getattr(ns, "file", "") or "").strip()
    if not explicit:
        return

    candidate = Path(explicit).expanduser().resolve()
    allowed_root = (paths.config_dir / "blueprints").resolve()
    try:
        candidate.relative_to(allowed_root)
    except ValueError as exc:
        raise ValueError(
            f"{command_label} requires --file to live under "
            f"{allowed_root} for the selected runtime. "
            "Copy the shipped blueprint there and rerun."
        ) from exc


def _emit(payload: dict[str, Any], *, json_mode: bool) -> None:
    if json_mode:
        print(json.dumps(payload, indent=2, sort_keys=True))
        return

    print(f"blueprint={payload.get('blueprint_ref','')} mode={payload.get('mode','')} status=ok")
    print(f"path={payload.get('path','')}")


def _emit_plan(payload: dict[str, Any], *, json_mode: bool) -> None:
    if json_mode:
        print(
            json.dumps(
                {
                    "blueprint_ref": payload["blueprint_ref"],
                    "mode": payload["mode"],
                    "policy": payload["policy"],
                    "path": payload["path"],
                    "order": payload["order"],
                    "steps": payload["steps"],
                },
                indent=2,
                sort_keys=True,
            )
        )
        return

    print(
        f"blueprint={payload['blueprint_ref']} mode={payload['mode']} plan_steps={len(payload['order'])}"
    )
    print("order:")
    for step_id in payload["order"]:
        step = next(s for s in payload["steps"] if s["id"] == step_id)
        print(f"  - {step_id}: {step['action']} {step['module_ref']} [{step['phase']}]")


def _default_overlay_name(blueprint_ref: str) -> str:
    raw = str(blueprint_ref or "").strip()
    name = raw.split("/", 1)[-1].split("@", 1)[0].strip()
    if not name:
        raise ValueError("unable to derive overlay file name from blueprint_ref")
    return f"{name}.yml"


def _normalize_dest_name(raw: str) -> str:
    candidate = str(raw or "").strip()
    if not candidate:
        raise ValueError("dest file name is empty")
    path = Path(candidate)
    if path.is_absolute() or len(path.parts) != 1 or candidate in {".", ".."}:
        raise ValueError("--dest-name must be a file name, not a path")
    suffix = path.suffix.lower()
    if not suffix:
        return f"{candidate}.yml"
    if suffix not in {".yml", ".yaml"}:
        raise ValueError("--dest-name must end in .yml or .yaml")
    return path.name


def _step_failure_detail(item: dict[str, Any]) -> str:
    checks = item.get("checks")
    if isinstance(checks, list):
        for check in checks:
            if not isinstance(check, dict):
                continue
            if bool(check.get("ok", False)):
                continue
            detail = str(check.get("detail") or "").strip()
            if detail:
                return detail
    return ""


def _evaluate_step_state_skip(step: dict[str, Any], paths) -> tuple[str, str]:
    contract = get_contract(step["module_ref"])
    return contract.evaluate_state_skip(
        command_name="deploy",
        module_ref=step["module_ref"],
        state_root=paths.state_dir,
        state_instance=str(step.get("state_instance") or "").strip() or None,
        credentials_dir=paths.credentials_dir,
        runtime_root=paths.root,
        env={str(k): str(v) for k, v in os.environ.items()},
    )


def _collect_deploy_risk_signals(payload: dict[str, Any], paths) -> list[dict[str, str]]:
    signals: list[dict[str, str]] = []
    for step in payload.get("steps", []):
        action = str(step.get("action") or "").strip().lower()
        if action not in {"apply", "deploy", "rebuild", "destroy"}:
            continue
        state_ref = step_state_ref(step)
        status = module_state_status(paths.state_dir, state_ref)
        if action in {"destroy", "rebuild"}:
            signals.append(
                {
                    "id": str(step.get("id") or ""),
                    "action": action,
                    "module_ref": str(step.get("module_ref") or ""),
                    "state_ref": state_ref,
                    "state_status": status or "missing",
                    "risk": "destructive",
                }
            )
            continue

        if not status:
            continue
        if bool(step.get("skip_if_state_ok", False)) and status == "ok":
            # This step should self-skip and does not need confirmation noise.
            continue
        signals.append(
            {
                "id": str(step.get("id") or ""),
                "action": action,
                "module_ref": str(step.get("module_ref") or ""),
                "state_ref": state_ref,
                "state_status": status,
                "risk": "rerun",
            }
        )
    return signals


def _confirm_deploy_if_needed(ns, payload: dict[str, Any], paths) -> int:
    if bool(getattr(ns, "yes", False)):
        return 0
    if bool(getattr(ns, "json", False)):
        return 0

    signals = _collect_deploy_risk_signals(payload, paths)
    if not signals:
        return 0

    env_name = str(getattr(ns, "env", None) or getattr(paths.root, "name", "") or "").strip() or "default"
    print(
        f"WARN: blueprint deploy may update or replace existing resources in env={env_name}."
    )
    print("impact_signals:")
    for item in signals:
        print(
            "  - "
            f"{item['id']}: {item['action']} {item['module_ref']} "
            f"(state={item['state_status']} ref={item['state_ref']})"
        )

    if not (sys.stdin.isatty() and sys.stdout.isatty()):
        print("WARN: non-interactive session detected; proceeding without prompt (use --yes to silence).")
        return 0

    try:
        answer = input("Proceed with blueprint deploy? [y/N]: ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        print()
        return CANCELLED
    if answer not in {"y", "yes"}:
        print("ERR: blueprint deploy cancelled by operator")
        return OPERATOR_ERROR
    return 0


def add_blueprint_subparser(sp: argparse._SubParsersAction) -> None:
    p = sp.add_parser("blueprint", help="Blueprint orchestration commands.")
    ssp = p.add_subparsers(dest="blueprint_cmd", required=True)

    def add_common_args(sub: argparse.ArgumentParser) -> None:
        sub.add_argument("--ref", default="", help="Blueprint ref, e.g. onprem/eve-ng@v1.")
        sub.add_argument("--file", default="", help="Explicit blueprint YAML path.")
        sub.add_argument(
            "--blueprints-root",
            default="blueprints",
            help="Blueprint root directory (default: blueprints from cwd or HYOPS_CORE_ROOT).",
        )
        sub.add_argument("--json", action="store_true", help="Emit JSON output.")

    i = ssp.add_parser(
        "init",
        help="Copy a shipped blueprint into the selected runtime config for operator editing.",
    )
    add_common_args(i)
    i.add_argument("--root", default=None, help="Override runtime root for blueprint overlay output.")
    i.add_argument("--env", default=None, help="Runtime environment namespace (e.g. dev, shared).")
    i.add_argument(
        "--dest-name",
        default="",
        help="Optional overlay file name (default: derived from blueprint ref, e.g. gcp-ops-runner.yml).",
    )
    i.add_argument(
        "--force",
        action="store_true",
        help="Overwrite an existing runtime blueprint overlay.",
    )
    i.set_defaults(_handler=run_init)

    q = ssp.add_parser("validate", help="Validate a blueprint manifest.")
    add_common_args(q)
    q.set_defaults(_handler=run_validate)

    u = ssp.add_parser(
        "preflight",
        help="Check contracts, module resolution, and driver preflight for each step.",
    )
    add_common_args(u)
    u.add_argument("--root", default=None, help="Override runtime root for state/contract checks.")
    u.add_argument("--env", default=None, help="Runtime environment namespace (e.g. dev, shared).")
    u.add_argument(
        "--module-root",
        default="modules",
        help="Module root directory for step resolution (default: modules from cwd or HYOPS_CORE_ROOT).",
    )
    u.set_defaults(_handler=run_preflight)

    r = ssp.add_parser("plan", help="Render blueprint execution order (skeleton).")
    add_common_args(r)
    r.set_defaults(_handler=run_plan)

    t = ssp.add_parser("deploy", help="Deploy blueprint steps in dependency order.")
    add_common_args(t)
    t.add_argument(
        "--execute",
        action="store_true",
        help="Execute ordered blueprint steps using module commands.",
    )
    t.add_argument("--root", default=None, help="Override runtime root for step execution.")
    t.add_argument("--env", default=None, help="Runtime environment namespace (e.g. dev, shared).")
    t.add_argument(
        "--module-root",
        default="modules",
        help="Module root directory for step execution (default: modules from cwd or HYOPS_CORE_ROOT).",
    )
    t.add_argument("--out-dir", default=None, help="Override evidence root for executed module steps.")
    t.add_argument(
        "--deps-inputs-dir",
        default=None,
        help="Optional dependency inputs directory for module steps that use --with-deps.",
    )
    t.add_argument(
        "--deps-force",
        action="store_true",
        help="Force dependency applies when step with_deps=true.",
    )
    t.add_argument(
        "--skip-preflight",
        action="store_true",
        help="Skip blueprint-level preflight gate before step execution.",
    )
    t.add_argument(
        "--yes",
        action="store_true",
        help="Proceed without interactive confirmation when rerun/destructive risk signals are detected.",
    )
    t.set_defaults(_handler=run_deploy)

    d = ssp.add_parser(
        "destroy",
        help="Destroy blueprint resources in reverse deployment order.",
    )
    add_common_args(d)
    d.add_argument(
        "--execute",
        action="store_true",
        help="Execute ordered blueprint step destruction.",
    )
    d.add_argument("--root", default=None, help="Override runtime root for step execution.")
    d.add_argument("--env", default=None, help="Runtime environment namespace (e.g. dev, shared).")
    d.add_argument(
        "--module-root",
        default="modules",
        help="Module root directory for step execution (default: modules from cwd or HYOPS_CORE_ROOT).",
    )
    d.add_argument("--out-dir", default=None, help="Override evidence root for executed module steps.")
    d.add_argument(
        "--yes",
        action="store_true",
        help="Proceed without interactive confirmation.",
    )
    d.set_defaults(_handler=run_destroy)


def run_validate(ns) -> int:
    try:
        payload = _resolve_and_validate(ns)
        _emit(payload, json_mode=bool(getattr(ns, "json", False)))
        return 0
    except Exception as exc:
        print(f"ERR: blueprint validation failed: {exc}")
        return OPERATOR_ERROR


def run_init(ns) -> int:
    try:
        require_runtime_selection(
            getattr(ns, "root", None),
            getattr(ns, "env", None),
            command_label="hyops blueprint init",
        )
        payload = _resolve_and_validate(ns)
        paths = resolve_runtime_paths(getattr(ns, "root", None), getattr(ns, "env", None))
        ensure_layout(paths)
        dest_dir = (paths.config_dir / "blueprints").resolve()
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest_name = _normalize_dest_name(
            getattr(ns, "dest_name", "") or _default_overlay_name(payload["blueprint_ref"])
        )
        dest_path = (dest_dir / dest_name).resolve()
        if dest_path.exists() and not bool(getattr(ns, "force", False)):
            raise FileExistsError(
                f"blueprint overlay already exists: {dest_path} "
                "(use --force to overwrite)"
            )
        shutil.copy2(Path(payload["path"]), dest_path)
        dest_path.chmod(0o600)
        out = {
            "blueprint_ref": payload["blueprint_ref"],
            "status": "initialized",
            "source": payload["path"],
            "file": str(dest_path),
        }
        if bool(getattr(ns, "json", False)):
            print(json.dumps(out, indent=2, sort_keys=True))
        else:
            print(f"blueprint={payload['blueprint_ref']} status=initialized")
            print(f"source={payload['path']}")
            print(f"file={dest_path}")
        return 0
    except Exception as exc:
        print(f"ERR: blueprint init failed: {exc}")
        return OPERATOR_ERROR


def run_preflight(ns) -> int:
    try:
        payload = _resolve_and_validate(ns)
    except Exception as exc:
        print(f"ERR: blueprint preflight failed: {exc}")
        return OPERATOR_ERROR

    try:
        require_runtime_selection(
            getattr(ns, "root", None),
            getattr(ns, "env", None),
            command_label="hyops blueprint preflight",
        )
        paths = resolve_runtime_paths(getattr(ns, "root", None), getattr(ns, "env", None))
        ensure_layout(paths)
        _enforce_runtime_blueprint_file_scope(
            ns,
            paths,
            command_label="hyops blueprint preflight",
        )
    except Exception as exc:
        print(f"ERR: blueprint preflight failed: {exc}")
        return OPERATOR_ERROR

    step_results, required_failures, optional_failures = compute_preflight(payload, ns, paths)

    status = "ok" if not required_failures else "failed"
    out = {
        "blueprint_ref": payload["blueprint_ref"],
        "mode": payload["mode"],
        "status": status,
        "path": payload["path"],
        "order": payload["order"],
        "required_failures": required_failures,
        "optional_failures": optional_failures,
        "steps": step_results,
    }

    if bool(getattr(ns, "json", False)):
        print(json.dumps(out, indent=2, sort_keys=True))
    else:
        print(
            f"blueprint={payload['blueprint_ref']} mode={payload['mode']} "
            f"preflight_status={status} steps={len(step_results)}"
        )
        for item in step_results:
            print(
                f"  - {item['id']}: {item['status']} "
                f"{item['action']} {item['module_ref']}"
            )
            if item["status"] == "blocked":
                detail = _step_failure_detail(item)
                if detail:
                    print(f"    reason: {detail}")
        if required_failures:
            print(f"required_failures: {', '.join(required_failures)}")
        if optional_failures:
            print(f"optional_failures: {', '.join(optional_failures)}")

    return 0 if not required_failures else OPERATOR_ERROR


def run_plan(ns) -> int:
    try:
        payload = _resolve_and_validate(ns)
        _emit_plan(payload, json_mode=bool(getattr(ns, "json", False)))
        return 0
    except Exception as exc:
        print(f"ERR: blueprint plan failed: {exc}")
        return OPERATOR_ERROR


def run_deploy(ns) -> int:
    try:
        payload = _resolve_and_validate(ns)
    except Exception as exc:
        print(f"ERR: blueprint deploy failed: {exc}")
        return OPERATOR_ERROR

    if not bool(getattr(ns, "execute", False)):
        if bool(getattr(ns, "json", False)):
            print(
                json.dumps(
                    {
                        "blueprint_ref": payload["blueprint_ref"],
                        "mode": payload["mode"],
                        "status": "skeleton",
                        "message": "Use --execute to run ordered step execution.",
                        "order": payload["order"],
                        "path": payload["path"],
                    },
                    indent=2,
                    sort_keys=True,
                )
            )
        else:
            print(f"blueprint={payload['blueprint_ref']} status=skeleton")
            print("execution disabled; validated order:")
            for step_id in payload["order"]:
                step = next(s for s in payload["steps"] if s["id"] == step_id)
                print(f"  - {step_id}: {step['action']} {step['module_ref']}")
        return 0

    json_mode = bool(getattr(ns, "json", False))
    try:
        require_runtime_selection(
            getattr(ns, "root", None),
            getattr(ns, "env", None),
            command_label="hyops blueprint deploy",
        )
        paths = resolve_runtime_paths(getattr(ns, "root", None), getattr(ns, "env", None))
        ensure_layout(paths)
        _enforce_runtime_blueprint_file_scope(
            ns,
            paths,
            command_label="hyops blueprint deploy",
        )
    except Exception as exc:
        print(f"ERR: blueprint deploy failed: {exc}")
        return OPERATOR_ERROR

    preflight_summary: dict[str, Any] | None = None
    if not bool(getattr(ns, "skip_preflight", False)):
        preflight_steps, preflight_required, preflight_optional = compute_preflight(payload, ns, paths)
        preflight_status = "ok" if not preflight_required else "failed"
        preflight_summary = {
            "status": preflight_status,
            "required_failures": list(preflight_required),
            "optional_failures": list(preflight_optional),
            "steps": preflight_steps,
        }
        if not json_mode:
            print(
                f"blueprint={payload['blueprint_ref']} mode={payload['mode']} "
                f"preflight_status={preflight_status} steps={len(preflight_steps)}"
            )
            for item in preflight_steps:
                if item["status"] != "blocked":
                    continue
                detail = _step_failure_detail(item)
                if detail:
                    print(f"  - {item['id']}: blocked {detail}")
            if preflight_required:
                print(f"required_failures: {', '.join(preflight_required)}")
            if preflight_optional:
                print(f"optional_failures: {', '.join(preflight_optional)}")
        if preflight_required:
            if json_mode:
                print(
                    json.dumps(
                        {
                            "blueprint_ref": payload["blueprint_ref"],
                            "mode": payload["mode"],
                            "status": "failed",
                            "phase": "preflight",
                            "preflight": preflight_summary,
                            "path": payload["path"],
                        },
                        indent=2,
                        sort_keys=True,
                    )
                )
            return OPERATOR_ERROR

    confirm_rc = _confirm_deploy_if_needed(ns, payload, paths)
    if confirm_rc != 0:
        if json_mode:
            print(
                json.dumps(
                    {
                        "blueprint_ref": payload["blueprint_ref"],
                        "mode": payload["mode"],
                        "status": "cancelled",
                        "phase": "confirmation",
                        "path": payload["path"],
                    },
                    indent=2,
                    sort_keys=True,
                )
            )
        return confirm_rc

    by_id = {step["id"]: step for step in payload["steps"]}
    fail_fast = bool(payload["policy"].get("fail_fast", True))
    step_results: list[dict[str, Any]] = []
    required_failures: list[str] = []
    optional_failures: list[str] = []
    cancelled = False

    for step_id in payload["order"]:
        step = by_id[step_id]
        base = {
            "id": step_id,
            "module_ref": step["module_ref"],
            "action": step["action"],
            "phase": step["phase"],
            "optional": bool(step.get("optional", False)),
        }

        # Materialize inline step inputs even if the step is skipped, so operators can
        # use the deterministic inputs file for destroy/rebuild workflows.
        try:
            inputs_file = resolved_step_inputs_file(step, payload, paths)
        except Exception as exc:
            inputs_file = None
            print(f"step={step_id} WARN: failed to materialize inputs file: {exc}")
        else:
            if inputs_file:
                base["inputs_file"] = str(inputs_file)

        if (
            bool(step.get("skip_if_state_ok", False))
            and step["action"] in ("apply", "deploy")
            and module_state_ok(paths.state_dir, step_state_ref(step))
        ):
            inputs_changed, inputs_detail = explicit_step_inputs_changed(step, payload, paths)
            if inputs_changed:
                drift_detail = "inputs-drift"
                if inputs_detail:
                    drift_detail = f"inputs-drift ({inputs_detail})"
                print(f"step={step_id} status=rerun reason={drift_detail}")
            else:
                verify_state_on_skip = bool(step.get("verify_state_on_skip", False))
                if not verify_state_on_skip:
                    result = dict(base)
                    result.update({"status": "skipped", "reason": "state-ok", "rc": 0})
                    step_results.append(result)
                    print(f"step={step_id} status=skipped reason=state-ok")
                    continue

                try:
                    skip_status, skip_detail = _evaluate_step_state_skip(step, paths)
                except Exception as exc:
                    skip_status = "error"
                    skip_detail = f"live state verification failed: {exc}"

                if skip_status == "safe":
                    detail = "state-ok"
                    if skip_detail:
                        detail = f"state-ok ({skip_detail})"
                    result = dict(base)
                    result.update({"status": "skipped", "reason": detail, "rc": 0})
                    step_results.append(result)
                    print(f"step={step_id} status=skipped reason={detail}")
                    continue

                if skip_status == "error":
                    result = dict(base)
                    result.update(
                        {
                            "status": "failed",
                            "reason": skip_detail or "live state verification failed",
                            "rc": OPERATOR_ERROR,
                        }
                    )
                    if step["optional"]:
                        result["status"] = "failed-optional"
                        optional_failures.append(step_id)
                        step_results.append(result)
                        print(f"step={step_id} status=failed-optional reason={result['reason']}")
                        continue

                    required_failures.append(step_id)
                    step_results.append(result)
                    print(f"step={step_id} status=failed reason={result['reason']}")
                    if fail_fast:
                        break
                    continue

                drift_detail = "live-state-drift"
                if skip_detail:
                    drift_detail = f"live-state-drift ({skip_detail})"
                print(f"step={step_id} status=rerun reason={drift_detail}")

        try:
            enforce_step_contracts(step, payload, paths)
        except Exception as exc:
            result = dict(base)
            result.update({"status": "failed", "reason": str(exc), "rc": OPERATOR_ERROR})
            if step["optional"]:
                result["status"] = "failed-optional"
                optional_failures.append(step_id)
                step_results.append(result)
                print(f"step={step_id} status=failed-optional reason={exc}")
                continue

            required_failures.append(step_id)
            step_results.append(result)
            print(f"step={step_id} status=failed reason={exc}")
            if fail_fast:
                break
            continue

        print(f"step={step_id} status=running action={step['action']} module={step['module_ref']}")
        try:
            rc = run_step_module_command(step, payload, ns, paths)
        except KeyboardInterrupt:
            rc = CANCELLED
            err = "cancelled by user"
        except Exception as exc:
            rc = OPERATOR_ERROR
            err = str(exc)
        else:
            err = ""

        if rc == 0:
            result = dict(base)
            result.update({"status": "ok", "rc": 0})
            step_results.append(result)
            print(f"step={step_id} status=ok")
            continue

        result = dict(base)
        result.update({"status": "failed", "rc": int(rc), "reason": err or "step command failed"})
        if int(rc) == CANCELLED:
            result["status"] = "cancelled"
            step_results.append(result)
            cancelled = True
            print(f"step={step_id} status=cancelled rc={rc}")
            break
        if step["optional"]:
            result["status"] = "failed-optional"
            optional_failures.append(step_id)
            step_results.append(result)
            print(f"step={step_id} status=failed-optional rc={rc}")
            continue

        required_failures.append(step_id)
        step_results.append(result)
        print(f"step={step_id} status=failed rc={rc}")
        if fail_fast:
            break

    final_status = "ok" if not required_failures else "failed"
    if cancelled:
        final_status = "cancelled"
    output = {
        "blueprint_ref": payload["blueprint_ref"],
        "mode": payload["mode"],
        "status": final_status,
        "fail_fast": fail_fast,
        "order": payload["order"],
        "path": payload["path"],
        "required_failures": required_failures,
        "optional_failures": optional_failures,
        "steps": step_results,
    }
    if preflight_summary is not None:
        output["preflight"] = preflight_summary

    if json_mode:
        print(json.dumps(output, indent=2, sort_keys=True))
    else:
        print(
            f"blueprint={payload['blueprint_ref']} mode={payload['mode']} "
            f"status={final_status} steps={len(step_results)}"
        )
        if required_failures:
            print(f"required_failures: {', '.join(required_failures)}")
        if optional_failures:
            print(f"optional_failures: {', '.join(optional_failures)}")

    if cancelled:
        return CANCELLED
    return 0 if not required_failures else OPERATOR_ERROR


def run_destroy(ns) -> int:
    try:
        payload = _resolve_and_validate(ns)
    except Exception as exc:
        print(f"ERR: blueprint destroy failed: {exc}")
        return OPERATOR_ERROR

    # Step execution order is the reverse of deployment order.
    destroy_order = list(reversed(payload["order"]))

    if not bool(getattr(ns, "execute", False)):
        if bool(getattr(ns, "json", False)):
            print(
                json.dumps(
                    {
                        "blueprint_ref": payload["blueprint_ref"],
                        "mode": payload["mode"],
                        "status": "skeleton",
                        "message": "Use --execute to run ordered step destruction.",
                        "order": destroy_order,
                        "path": payload["path"],
                    },
                    indent=2,
                    sort_keys=True,
                )
            )
        else:
            print(f"blueprint={payload['blueprint_ref']} status=skeleton")
            print("execution disabled; destroy order:")
            for step_id in destroy_order:
                step = next(s for s in payload["steps"] if s["id"] == step_id)
                print(f"  - {step_id}: destroy {step['module_ref']}")
        return 0

    json_mode = bool(getattr(ns, "json", False))
    try:
        require_runtime_selection(
            getattr(ns, "root", None),
            getattr(ns, "env", None),
            command_label="hyops blueprint destroy",
        )
        paths = resolve_runtime_paths(getattr(ns, "root", None), getattr(ns, "env", None))
        ensure_layout(paths)
        _enforce_runtime_blueprint_file_scope(
            ns,
            paths,
            command_label="hyops blueprint destroy",
        )
    except Exception as exc:
        print(f"ERR: blueprint destroy failed: {exc}")
        return OPERATOR_ERROR

    by_id = {step["id"]: step for step in payload["steps"]}

    if not bool(getattr(ns, "yes", False)) and not json_mode:
        env_name = (
            str(getattr(ns, "env", None) or getattr(paths.root, "name", "") or "").strip()
            or "default"
        )
        print(f"WARN: blueprint destroy will tear down resources in env={env_name}.")
        print("steps (reverse order):")
        for step_id in destroy_order:
            step = by_id[step_id]
            state_ref = step_state_ref(step)
            status = module_state_status(paths.state_dir, state_ref) or "missing"
            print(
                f"  - {step_id}: destroy {step['module_ref']} "
                f"(state={status} ref={state_ref})"
            )

        if sys.stdin.isatty() and sys.stdout.isatty():
            try:
                answer = input("Proceed with blueprint destroy? [y/N]: ").strip().lower()
            except (EOFError, KeyboardInterrupt):
                print()
                return CANCELLED
            if answer not in {"y", "yes"}:
                print("ERR: blueprint destroy cancelled by operator")
                return OPERATOR_ERROR
        else:
            print(
                "WARN: non-interactive session detected; proceeding without prompt "
                "(use --yes to silence)."
            )

    fail_fast = bool(payload["policy"].get("fail_fast", True))
    step_results: list[dict[str, Any]] = []
    required_failures: list[str] = []
    optional_failures: list[str] = []
    cancelled = False

    for step_id in destroy_order:
        step = by_id[step_id]
        # Override action to destroy regardless of what the blueprint step declares.
        destroy_step = dict(step)
        destroy_step["action"] = "destroy"

        base = {
            "id": step_id,
            "module_ref": step["module_ref"],
            "action": "destroy",
            "phase": step["phase"],
            "optional": bool(step.get("optional", False)),
        }

        # Materialize inputs file so operators have a rerun path even on skip.
        try:
            inputs_file = resolved_step_inputs_file(step, payload, paths)
        except Exception as exc:
            inputs_file = None
            print(f"step={step_id} WARN: failed to materialize inputs file: {exc}")
        else:
            if inputs_file:
                base["inputs_file"] = str(inputs_file)

        # Skip steps with no recorded state — nothing to destroy.
        state_ref = step_state_ref(step)
        if not module_state_status(paths.state_dir, state_ref):
            result = dict(base)
            result.update({"status": "skipped", "reason": "no-state", "rc": 0})
            step_results.append(result)
            print(f"step={step_id} status=skipped reason=no-state")
            continue

        print(f"step={step_id} status=running action=destroy module={step['module_ref']}")
        try:
            rc = run_step_module_command(destroy_step, payload, ns, paths)
        except KeyboardInterrupt:
            rc = CANCELLED
            err = "cancelled by user"
        except Exception as exc:
            rc = OPERATOR_ERROR
            err = str(exc)
        else:
            err = ""

        if rc == 0:
            result = dict(base)
            result.update({"status": "ok", "rc": 0})
            step_results.append(result)
            print(f"step={step_id} status=ok")
            continue

        result = dict(base)
        result.update({"status": "failed", "rc": int(rc), "reason": err or "step command failed"})
        if int(rc) == CANCELLED:
            result["status"] = "cancelled"
            step_results.append(result)
            cancelled = True
            print(f"step={step_id} status=cancelled rc={rc}")
            break
        if step["optional"]:
            result["status"] = "failed-optional"
            optional_failures.append(step_id)
            step_results.append(result)
            print(f"step={step_id} status=failed-optional rc={rc}")
            continue

        required_failures.append(step_id)
        step_results.append(result)
        print(f"step={step_id} status=failed rc={rc}")
        if fail_fast:
            break

    final_status = "ok" if not required_failures else "failed"
    if cancelled:
        final_status = "cancelled"
    output = {
        "blueprint_ref": payload["blueprint_ref"],
        "mode": payload["mode"],
        "status": final_status,
        "fail_fast": fail_fast,
        "order": destroy_order,
        "path": payload["path"],
        "required_failures": required_failures,
        "optional_failures": optional_failures,
        "steps": step_results,
    }

    if json_mode:
        print(json.dumps(output, indent=2, sort_keys=True))
    else:
        print(
            f"blueprint={payload['blueprint_ref']} mode={payload['mode']} "
            f"status={final_status} steps={len(step_results)}"
        )
        if required_failures:
            print(f"required_failures: {', '.join(required_failures)}")
        if optional_failures:
            print(f"optional_failures: {', '.join(optional_failures)}")

    if cancelled:
        return CANCELLED
    return 0 if not required_failures else OPERATOR_ERROR


__all__ = [
    "add_blueprint_subparser",
    "run_validate",
    "run_preflight",
    "run_plan",
    "run_deploy",
    "run_destroy",
]
