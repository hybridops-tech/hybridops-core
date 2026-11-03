"""Run and inspect the isolated HybridOps quickstart operation."""

from __future__ import annotations

import argparse
import io
import json
import sys
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from typing import Any

from hyops.commands._apply_execute import run_single
from hyops.drivers.local.artifact import inspect_runtime_artifact
from hyops.runtime.layout import ensure_layout
from hyops.runtime.module_resolve import resolve_module
from hyops.runtime.module_state import module_state_path, read_module_state
from hyops.runtime.paths import RuntimePaths
from hyops.runtime.source_roots import resolve_module_root


_MODULE_REF = "core/local/quickstart"
_RUNTIME_DIRECTORIES = {
    "config",
    "credentials",
    "logs",
    "meta",
    "state",
    "vault",
    "work",
}


def _default_root() -> Path:
    return Path.home() / ".hybridops" / "quickstart"


def add_quickstart_subparser(sp: argparse._SubParsersAction) -> None:
    parser = sp.add_parser(
        "quickstart",
        help="Run a credential-free HybridOps operation and inspect its record.",
    )
    parser.add_argument(
        "action",
        nargs="?",
        default="run",
        choices=("run", "status", "reset"),
        help="Operation to perform (default: run).",
    )
    parser.add_argument(
        "--root",
        default=None,
        help="Override the isolated quickstart runtime root.",
    )
    parser.add_argument("--json", action="store_true", help="Emit JSON.")
    parser.set_defaults(_handler=run)


def _paths(root: str | None) -> RuntimePaths:
    selected = Path(root).expanduser() if root else _default_root()
    if selected.is_symlink():
        raise ValueError("quickstart runtime root must not be a symbolic link")
    return RuntimePaths.from_root(selected)


def _validate_isolated_root(paths: RuntimePaths) -> None:
    root = paths.root
    if root.exists() and not root.is_dir():
        raise ValueError("quickstart runtime root must be a directory")

    if root.exists():
        unknown = sorted(
            entry.name for entry in root.iterdir() if entry.name not in _RUNTIME_DIRECTORIES
        )
        if unknown:
            raise ValueError(
                "quickstart runtime root contains unrelated entries: "
                + ", ".join(unknown)
            )

        pending = [root]
        while pending:
            directory = pending.pop()
            for entry in directory.iterdir():
                if entry.is_symlink():
                    raise ValueError(
                        f"quickstart runtime must not contain symbolic links: {entry}"
                    )
                if entry.is_dir():
                    pending.append(entry)

    try:
        default_runtime = _default_root().parent.resolve()
    except RuntimeError:
        default_runtime = None
    if default_runtime is not None:
        environments_root = default_runtime / "envs"
        if root == default_runtime or root.parent == environments_root:
            raise ValueError("quickstart cannot use a normal HybridOps environment root")

    if any(paths.meta_dir.glob("*.ready.json")):
        raise ValueError("quickstart cannot use an initialized runtime root")
    if any((paths.config_dir / "blueprints").glob("*.y*ml")):
        raise ValueError("quickstart cannot use a runtime root with initialized blueprints")

    modules_root = paths.state_dir / "modules"
    if modules_root.is_dir():
        other_modules = [
            path.name
            for path in modules_root.iterdir()
            if path.name != "core__local__quickstart"
        ]
        if other_modules:
            raise ValueError("quickstart cannot use a runtime root with other module state")


def _root_error(message: str, *, as_json: bool) -> int:
    if as_json:
        print(json.dumps({"status": "error", "error": message}, indent=2, sort_keys=True))
    else:
        print(f"ERR: {message}", file=sys.stderr)
    return 2


def _artifact_observation(paths: RuntimePaths) -> dict[str, Any]:
    resolved = resolve_module(
        _MODULE_REF,
        resolve_module_root("modules"),
        None,
        state_dir=paths.state_dir,
        runtime_root=paths.root,
    )
    return inspect_runtime_artifact(
        {
            "module_ref": resolved.module_ref,
            "execution": resolved.execution,
            "runtime": {
                "root": str(paths.root),
                "state_dir": str(paths.state_dir),
            },
        }
    )


def _status_payload(paths: RuntimePaths) -> dict[str, Any]:
    state_path = module_state_path(paths.state_dir, _MODULE_REF)
    try:
        observation = _artifact_observation(paths)
    except Exception as exc:
        observation = {"status": "unsafe", "error": str(exc)}
    try:
        state = read_module_state(paths.state_dir, _MODULE_REF)
    except FileNotFoundError:
        state = {}
    except Exception as exc:
        return {
            "status": "invalid",
            "error": str(exc),
            "runtime_root": str(paths.root),
            "state_path": str(state_path),
            "artifact": observation,
        }

    state_status = str(state.get("status") or "").strip().lower()
    outputs = state.get("outputs")
    if not isinstance(outputs, dict):
        outputs = {}

    artifact_status = str(observation.get("status") or "unknown")
    artifact_sha = str(observation.get("artifact_sha256") or "")
    expected_sha = str(outputs.get("quickstart.artifact_sha256") or "")

    if not state and artifact_status == "absent":
        status = "not_started"
    elif state_status == "destroyed" and artifact_status == "absent":
        status = "reset"
    elif (
        state_status == "ok"
        and artifact_status == "present"
        and bool(outputs.get("quickstart.verified"))
        and bool(expected_sha)
        and artifact_sha == expected_sha
    ):
        status = "ready"
    else:
        status = "drifted"

    return {
        "status": status,
        "runtime_root": str(paths.root),
        "state_path": str(state_path),
        "state_status": state_status or "absent",
        "operation_id": str(outputs.get("quickstart.operation_id") or ""),
        "declared_outcome": str(outputs.get("quickstart.declared_outcome") or ""),
        "evidence_dir": str(state.get("evidence_dir") or ""),
        "artifact": observation,
    }


def _print_status(payload: dict[str, Any]) -> int:
    status = str(payload.get("status") or "unknown")
    if status == "not_started":
        print("Quickstart has not been run.")
        print("Run: hyops quickstart")
        return 0
    if status == "reset":
        print("Quickstart is reset. No managed artifact is present.")
        return 0
    if status != "ready":
        print("Quickstart state does not match the managed artifact.", file=sys.stderr)
        print("Run: hyops quickstart reset", file=sys.stderr)
        return 1

    artifact = payload.get("artifact")
    artifact_path = artifact.get("artifact_path", "") if isinstance(artifact, dict) else ""
    print("Quickstart is ready.")
    print(f"operation: {payload.get('operation_id', '')}")
    print(f"outcome: {payload.get('declared_outcome', '')}")
    print(f"artifact: {artifact_path}")
    print(f"run record: {payload.get('evidence_dir', '')}")
    return 0


def _run_record(output: str) -> str:
    records = [
        line.strip()
        for line in output.splitlines()
        if line.strip().lower().startswith("run record:")
    ]
    return records[-1] if records else ""


def _execution_error(
    paths: RuntimePaths,
    *,
    command: str,
    message: str,
    as_json: bool,
) -> int:
    if as_json:
        print(
            json.dumps(
                {
                    "status": "error",
                    "command": command,
                    "error": message,
                    "runtime_root": str(paths.root),
                    "exit_code": 1,
                },
                indent=2,
                sort_keys=True,
            )
        )
    else:
        print(f"ERR: {message}", file=sys.stderr)
    return 1


def _execute(paths: RuntimePaths, *, command: str, as_json: bool) -> int:
    try:
        ensure_layout(paths, reject_symlinks=True)
    except (OSError, RuntimeError, ValueError) as exc:
        return _execution_error(
            paths,
            command=command,
            message=f"failed to prepare quickstart runtime: {exc}",
            as_json=as_json,
        )

    stdout = io.StringIO()
    stderr = io.StringIO()

    def invoke() -> int:
        return run_single(
            paths=paths,
            env_name=None,
            command_name=command,
            module_ref_raw=_MODULE_REF,
            module_root=resolve_module_root("modules"),
            inputs_file=None,
            out_dir=None,
            skip_preflight=False,
            state_instance=None,
        )

    try:
        with redirect_stdout(stdout), redirect_stderr(stderr):
            rc = invoke()
    except Exception as exc:
        return _execution_error(
            paths,
            command=command,
            message=f"quickstart execution failed: {exc}",
            as_json=as_json,
        )

    payload = _status_payload(paths)
    payload["command"] = command
    payload["exit_code"] = rc
    if rc != 0:
        diagnostic = stderr.getvalue().strip().splitlines()
        if diagnostic:
            payload["error"] = diagnostic[-1]
        record = _run_record("\n".join((stdout.getvalue(), stderr.getvalue())))
        if record:
            payload["run_record"] = record.removeprefix("run record:").strip()

    if as_json:
        print(json.dumps(payload, indent=2, sort_keys=True))
    elif rc != 0:
        if stderr.getvalue().strip():
            print(stderr.getvalue().strip(), file=sys.stderr)
        if record and record not in stderr.getvalue():
            print(record, file=sys.stderr)
        elif not stderr.getvalue().strip() and stdout.getvalue().strip():
            print(stdout.getvalue().strip(), file=sys.stderr)
    else:
        if command == "destroy":
            print("Quickstart reset complete.")
        else:
            print("Quickstart complete.")
            print(f"operation: {payload.get('operation_id', '')}")
            print(f"outcome: {payload.get('declared_outcome', '')}")
            artifact = payload.get("artifact")
            artifact_path = (
                artifact.get("artifact_path", "") if isinstance(artifact, dict) else ""
            )
            print(f"artifact: {artifact_path}")
            print(f"state: {payload.get('state_path', '')}")
            print(f"run record: {payload.get('evidence_dir', '')}")
    return rc


def run(ns: argparse.Namespace) -> int:
    action = str(getattr(ns, "action", "run") or "run")
    as_json = bool(getattr(ns, "json", False))
    try:
        paths = _paths(getattr(ns, "root", None))
        _validate_isolated_root(paths)
    except (OSError, RuntimeError, ValueError) as exc:
        return _root_error(str(exc), as_json=as_json)

    if action == "status":
        payload = _status_payload(paths)
        if as_json:
            print(json.dumps(payload, indent=2, sort_keys=True))
            return 0 if payload.get("status") in {"not_started", "ready", "reset"} else 1
        return _print_status(payload)
    if action == "reset":
        return _execute(paths, command="destroy", as_json=as_json)
    return _execute(paths, command="apply", as_json=as_json)
