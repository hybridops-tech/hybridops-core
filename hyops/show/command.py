"""
purpose: Read-only state-backed operator views for init, module, and env.
Architecture Decision: ADR-N/A (show command)
maintainer: HybridOps.Tech
"""

from __future__ import annotations

import argparse
import json
import os
import shlex
import subprocess
import sys
from collections import Counter
from pathlib import Path
from typing import Any

from hyops.runtime.exitcodes import OK, OPERATOR_ERROR
from hyops.runtime.module_state import read_module_state
from hyops.runtime.paths import resolve_runtime_paths
from hyops.runtime.readiness import read_marker
from hyops.runtime.root import require_runtime_selection


def add_show_subparser(sp: argparse._SubParsersAction) -> None:
    p = sp.add_parser("show", help="Show state-backed init, module, and env views.")
    ssp = p.add_subparsers(dest="show_cmd", required=True)

    q = ssp.add_parser("init", help="Show init readiness markers for an environment.")
    q.add_argument("target", nargs="?", help="Init target name (for example: gcp).")
    q.add_argument("--root", default=None, help="Override runtime root.")
    q.add_argument("--env", default=None, help="Runtime environment namespace.")
    q.add_argument("--json", action="store_true", help="Emit JSON.")
    q.set_defaults(_handler=run_show_init)

    q = ssp.add_parser("module", help="Show normalized module state.")
    q.add_argument(
        "module_ref",
        help="Module ref, optionally with state instance (for example: platform/network/decision-service or org/hetzner/shared-control-host#edge_control_host).",
    )
    q.add_argument("--root", default=None, help="Override runtime root.")
    q.add_argument("--env", default=None, help="Runtime environment namespace.")
    q.add_argument("--json", action="store_true", help="Emit JSON.")
    q.set_defaults(_handler=run_show_module)

    q = ssp.add_parser("env", help="Show a summarized environment view from runtime state.")
    q.add_argument("--root", default=None, help="Override runtime root.")
    q.add_argument("--env", default=None, help="Runtime environment namespace.")
    q.add_argument("--json", action="store_true", help="Emit JSON.")
    q.set_defaults(_handler=run_show_env)


def _resolve_paths(ns, *, label: str) -> Any:
    try:
        require_runtime_selection(getattr(ns, "root", None), getattr(ns, "env", None), command_label=label)
        return resolve_runtime_paths(getattr(ns, "root", None), getattr(ns, "env", None))
    except Exception as exc:
        print(f"ERR: {exc}", file=sys.stderr)
        raise


def _emit_json(payload: dict[str, Any]) -> int:
    print(json.dumps(payload, indent=2, sort_keys=True))
    return OK


def _marker_target(path: Path) -> str:
    name = path.name
    suffix = ".ready.json"
    return name[:-len(suffix)] if name.endswith(suffix) else name


def _list_markers(meta_dir: Path) -> list[dict[str, Any]]:
    markers: list[dict[str, Any]] = []
    for path in sorted(meta_dir.glob("*.ready.json")):
        target = _marker_target(path)
        try:
            payload = read_marker(meta_dir, target)
        except Exception as exc:
            markers.append(
                {
                    "target": target,
                    "status": "invalid",
                    "error": str(exc),
                    "path": str(path),
                }
            )
            continue
        if isinstance(payload, dict):
            payload = dict(payload)
            payload.setdefault("target", target)
            markers.append(payload)
    return markers


def _module_latest_paths(state_dir: Path) -> list[Path]:
    return sorted(state_dir.glob("modules/*/latest.json"))


def _module_instance_paths(state_dir: Path) -> list[Path]:
    return sorted(state_dir.glob("modules/*/instances/*.json"))


def _read_json_file(path: Path) -> dict[str, Any] | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _format_scalar(value: Any) -> str:
    def _clip(text: str, *, limit: int = 160) -> str:
        if len(text) <= limit:
            return text
        return f"{text[: limit - 3]}..."

    if isinstance(value, bool):
        return "true" if value else "false"
    if value is None:
        return "null"
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, str):
        return _clip(value)
    return _clip(json.dumps(value, sort_keys=True))


def _print_outputs(outputs: dict[str, Any], *, limit: int = 12) -> None:
    if not outputs:
        print("outputs: none")
        return
    print("outputs:")
    items = sorted(outputs.items(), key=lambda item: item[0])
    for key, value in items[:limit]:
        print(f"  {key}: {_format_scalar(value)}")
    remainder = len(items) - limit
    if remainder > 0:
        print(f"  ... {remainder} more")


def _normalize_module_ref(value: str) -> str:
    token = str(value or "").strip().replace(".", "/")
    while "//" in token:
        token = token.replace("//", "/")
    return token.strip("/")


def _extract_primary_ip(outputs: dict[str, Any]) -> str:
    direct = str(outputs.get("public_ipv4") or outputs.get("ipv4_configured_primary") or "").strip()
    if direct:
        return direct

    mapped = outputs.get("ipv4_configured_primary")
    if isinstance(mapped, dict):
        for key in sorted(mapped):
            value = str(mapped.get(key) or "").strip()
            if value:
                return value

    vms = outputs.get("vms")
    if isinstance(vms, dict):
        for key in sorted(vms):
            item = vms.get(key)
            if not isinstance(item, dict):
                continue
            value = str(item.get("ipv4_configured_primary") or item.get("ipv4_address") or "").strip()
            if value:
                return value
    return ""


def _decision_service_live_state(paths, payload: dict[str, Any]) -> dict[str, Any]:
    module_ref = _normalize_module_ref(str(payload.get("module_ref") or ""))
    if module_ref != "platform/network/decision-service":
        return {}

    input_contract = payload.get("input_contract")
    if not isinstance(input_contract, dict):
        return {
            "available": False,
            "error": "missing_input_contract",
        }

    inventory_state_ref = str(input_contract.get("inventory_state_ref") or "").strip()
    if not inventory_state_ref:
        return {
            "available": False,
            "error": "missing_inventory_state_ref",
        }

    try:
        host_payload = read_module_state(paths.state_dir, inventory_state_ref)
    except Exception as exc:
        return {
            "available": False,
            "error": f"inventory_state_read_failed:{exc}",
            "inventory_state_ref": inventory_state_ref,
        }

    outputs = host_payload.get("outputs")
    if not isinstance(outputs, dict):
        return {
            "available": False,
            "error": "inventory_outputs_missing",
            "inventory_state_ref": inventory_state_ref,
        }

    host = _extract_primary_ip(outputs)
    if not host:
        return {
            "available": False,
            "error": "inventory_host_ip_missing",
            "inventory_state_ref": inventory_state_ref,
        }

    ssh_user = str(os.environ.get("HYOPS_SHOW_SSH_USER") or "opsadmin").strip() or "opsadmin"
    state_file = str(
        os.environ.get("HYOPS_SHOW_DECISION_SERVICE_STATE_FILE")
        or "/opt/hybridops/decision-service/state/state.json"
    ).strip()

    try:
        proc = subprocess.run(
            [
                "ssh",
                "-o",
                "BatchMode=yes",
                "-o",
                "StrictHostKeyChecking=no",
                "-o",
                "ConnectTimeout=5",
                f"{ssh_user}@{host}",
                f"sudo cat {shlex.quote(state_file)}",
            ],
            capture_output=True,
            text=True,
            timeout=8,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return {
            "available": False,
            "error": "ssh_timeout",
            "host": host,
            "ssh_user": ssh_user,
            "state_file": state_file,
        }
    except Exception as exc:
        return {
            "available": False,
            "error": f"ssh_exec_failed:{exc}",
            "host": host,
            "ssh_user": ssh_user,
            "state_file": state_file,
        }

    if proc.returncode != 0:
        stderr = str(proc.stderr or "").strip()
        return {
            "available": False,
            "error": f"ssh_rc_{proc.returncode}",
            "host": host,
            "ssh_user": ssh_user,
            "state_file": state_file,
            "stderr": stderr[-200:] if stderr else "",
        }

    try:
        live_payload = json.loads(proc.stdout or "{}")
    except Exception as exc:
        return {
            "available": False,
            "error": f"invalid_live_json:{exc}",
            "host": host,
            "ssh_user": ssh_user,
            "state_file": state_file,
        }

    if not isinstance(live_payload, dict):
        return {
            "available": False,
            "error": "invalid_live_payload",
            "host": host,
            "ssh_user": ssh_user,
            "state_file": state_file,
        }

    return {
        "available": True,
        "host": host,
        "ssh_user": ssh_user,
        "state_file": state_file,
        "mode": str(live_payload.get("mode") or ""),
        "reason": str(live_payload.get("reason") or ""),
        "recommended_action": str(live_payload.get("recommended_action") or ""),
        "last_action": str(live_payload.get("last_action") or ""),
        "last_action_rc": live_payload.get("last_action_rc"),
        "last_decision_id": str(live_payload.get("last_decision_id") or ""),
        "signal_ready": live_payload.get("signal_ready"),
        "status": str(live_payload.get("status") or ""),
        "timestamp_utc": str(live_payload.get("timestamp_utc") or ""),
    }


def _print_section(title: str, payload: dict[str, Any]) -> None:
    if not payload:
        return
    print(f"{title}:")
    for key, value in sorted(payload.items(), key=lambda item: item[0]):
        print(f"  {key}: {_format_scalar(value)}")


def run_show_init(ns) -> int:
    try:
        paths = _resolve_paths(ns, label="show init")
    except Exception:
        return OPERATOR_ERROR

    target = str(getattr(ns, "target", "") or "").strip()
    if target:
        try:
            payload = read_marker(paths.meta_dir, target)
        except FileNotFoundError:
            print(f"ERR: init target not found: {target}", file=sys.stderr)
            return OPERATOR_ERROR
        except Exception as exc:
            print(f"ERR: failed to read init marker for {target}: {exc}", file=sys.stderr)
            return 1
        if getattr(ns, "json", False):
            return _emit_json(payload)

        status = str(payload.get("status") or "unknown")
        run_id = str(payload.get("run_id") or "").strip()
        print(f"target={target} status={status}")
        if run_id:
            print(f"run_id={run_id}")
        context = payload.get("context")
        if isinstance(context, dict) and context:
            print("context:")
            for key, value in sorted(context.items(), key=lambda item: item[0]):
                print(f"  {key}: {_format_scalar(value)}")
        paths_obj = payload.get("paths")
        if isinstance(paths_obj, dict) and paths_obj:
            record = str(paths_obj.get("evidence_dir") or "").strip()
            if record:
                print(f"run record: {record}")
            for key, value in sorted(paths_obj.items(), key=lambda item: item[0]):
                if key == "evidence_dir":
                    continue
                print(f"{key}: {_format_scalar(value)}")
        return OK

    markers = _list_markers(paths.meta_dir)
    payload = {"env_root": str(paths.root), "markers": markers}
    if getattr(ns, "json", False):
        return _emit_json(payload)

    print(f"env_root={paths.root}")
    if not markers:
        print("markers: none")
        return OK
    print("markers:")
    for item in markers:
        marker_target = str(item.get("target") or "unknown")
        status = str(item.get("status") or "unknown")
        run_id = str(item.get("run_id") or "").strip()
        suffix = f" run_id={run_id}" if run_id else ""
        print(f"  {marker_target}: {status}{suffix}")
    return OK


def run_show_module(ns) -> int:
    try:
        paths = _resolve_paths(ns, label="show module")
    except Exception:
        return OPERATOR_ERROR

    module_ref = str(getattr(ns, "module_ref", "") or "").strip()
    try:
        payload = read_module_state(paths.state_dir, module_ref)
    except FileNotFoundError:
        print(f"ERR: module state not found: {module_ref}", file=sys.stderr)
        return OPERATOR_ERROR
    except Exception as exc:
        print(f"ERR: failed to read module state for {module_ref}: {exc}", file=sys.stderr)
        return 1

    live_state = _decision_service_live_state(paths, payload)
    if live_state:
        payload = dict(payload)
        payload["live_state"] = live_state

    if getattr(ns, "json", False):
        return _emit_json(payload)

    resolved_ref = str(payload.get("module_ref") or module_ref)
    status = str(payload.get("status") or "unknown")
    print(f"module={resolved_ref} status={status}")

    state_instance = str(payload.get("state_instance") or "").strip()
    if state_instance:
        print(f"state_instance={state_instance}")

    run_id = str(payload.get("run_id") or "").strip()
    updated_at = str(payload.get("updated_at") or "").strip()
    if run_id:
        print(f"run_id={run_id}")
    if updated_at:
        print(f"updated_at={updated_at}")

    execution = payload.get("execution")
    if isinstance(execution, dict) and execution:
        driver = str(execution.get("driver") or "").strip()
        profile = str(execution.get("profile") or "").strip()
        pack_id = str(execution.get("pack_id") or "").strip()
        if driver:
            print(f"driver={driver}")
        if profile:
            print(f"profile={profile}")
        if pack_id:
            print(f"pack={pack_id}")

    input_contract = payload.get("input_contract")
    if isinstance(input_contract, dict) and input_contract:
        print("input_contract:")
        for key, value in sorted(input_contract.items(), key=lambda item: item[0]):
            print(f"  {key}: {_format_scalar(value)}")

    outputs = payload.get("outputs")
    if isinstance(outputs, dict):
        _print_outputs(outputs)
    else:
        print("outputs: none")

    live_state_payload = payload.get("live_state")
    if isinstance(live_state_payload, dict) and live_state_payload:
        _print_section("live_state", live_state_payload)

    record = str(payload.get("evidence_dir") or "").strip()
    if record:
        print(f"run record: {record}")
    rerun = str(payload.get("rerun_inputs_file") or "").strip()
    if rerun:
        print(f"rerun_inputs: {rerun}")
    resolved_inputs = str(payload.get("resolved_inputs_file") or "").strip()
    if resolved_inputs:
        print(f"resolved_inputs: {resolved_inputs}")
    return OK


def run_show_env(ns) -> int:
    try:
        paths = _resolve_paths(ns, label="show env")
    except Exception:
        return OPERATOR_ERROR

    markers = _list_markers(paths.meta_dir)
    latest_states: list[dict[str, Any]] = []
    invalid_latest_files: list[str] = []
    for path in _module_latest_paths(paths.state_dir):
        payload = _read_json_file(path)
        if isinstance(payload, dict):
            latest_states.append(payload)
        else:
            invalid_latest_files.append(str(path))

    instance_files = _module_instance_paths(paths.state_dir)
    marker_counts = Counter(str(item.get("status") or "unknown") for item in markers)
    module_counts = Counter(str(item.get("status") or "unknown") for item in latest_states)

    capabilities: list[dict[str, str]] = []
    for state in latest_states:
        module_ref = str(state.get("module_ref") or "").strip()
        outputs = state.get("outputs")
        if not module_ref or not isinstance(outputs, dict):
            continue
        for key, value in sorted(outputs.items(), key=lambda item: item[0]):
            if not str(key).startswith("cap."):
                continue
            capabilities.append(
                {
                    "module_ref": module_ref,
                    "key": str(key),
                    "value": _format_scalar(value),
                }
            )

    non_ok_modules: list[dict[str, str]] = []
    for state in latest_states:
        status = str(state.get("status") or "unknown")
        if status == "ok":
            continue
        non_ok_modules.append(
            {
                "module_ref": str(state.get("module_ref") or "unknown"),
                "status": status,
                "run_id": str(state.get("run_id") or ""),
            }
        )

    payload = {
        "env_root": str(paths.root),
        "init_markers": {
            "count": len(markers),
            "status_counts": dict(sorted(marker_counts.items())),
            "targets": [str(item.get("target") or "unknown") for item in markers],
        },
        "module_state": {
            "latest_count": len(latest_states),
            "instance_count": len(instance_files),
            "status_counts": dict(sorted(module_counts.items())),
            "invalid_latest_files": invalid_latest_files,
            "non_ok_modules": non_ok_modules,
        },
        "capabilities": capabilities,
    }
    if getattr(ns, "json", False):
        return _emit_json(payload)

    print(f"env_root={paths.root}")
    print(
        "init_markers="
        f"{len(markers)} "
        f"status_counts={json.dumps(dict(sorted(marker_counts.items())), sort_keys=True)}"
    )
    print(
        "module_state="
        f"latest:{len(latest_states)} "
        f"instances:{len(instance_files)} "
        f"status_counts={json.dumps(dict(sorted(module_counts.items())), sort_keys=True)}"
    )
    if non_ok_modules:
        print("non_ok_modules:")
        for item in non_ok_modules[:12]:
            module_ref = item.get("module_ref", "unknown")
            status = item.get("status", "unknown")
            run_id = item.get("run_id", "")
            suffix = f" run_id={run_id}" if run_id else ""
            print(f"  {module_ref}: {status}{suffix}")
        remainder = len(non_ok_modules) - 12
        if remainder > 0:
            print(f"  ... {remainder} more")
    else:
        print("non_ok_modules: none")

    if capabilities:
        print("capabilities:")
        for item in capabilities[:20]:
            print(f"  {item['key']}: {item['value']} ({item['module_ref']})")
        remainder = len(capabilities) - 20
        if remainder > 0:
            print(f"  ... {remainder} more")
    else:
        print("capabilities: none")
    return OK


__all__ = [
    "add_show_subparser",
    "run_show_env",
    "run_show_init",
    "run_show_module",
]
