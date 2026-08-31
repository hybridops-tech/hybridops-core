"""Blueprint CLI commands."""

from __future__ import annotations

import argparse
import base64
import errno
import hashlib
import ipaddress
import json
import os
import re
import shlex
import shutil
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any, Callable

import yaml

from hyops.drivers.iac.terragrunt.contracts import get_contract
from hyops.runtime.browser import is_windows_wsl, open_operator_url
from hyops.runtime.cost import CostEstimate, format_money
from hyops.runtime.evidence import EvidenceWriter, new_run_id
from hyops.runtime.exitcodes import CANCELLED, OPERATOR_ERROR
from hyops.runtime.gcp import diagnose_project_billing
from hyops.runtime.gcp_cost import estimate_gcp_vm_cost, gcp_vm_lifecycle_started_at
from hyops.runtime.layout import ensure_layout
from hyops.runtime.module_state import (
    read_module_state,
    split_module_state_ref,
    write_module_state,
)
from hyops.runtime.operator_output import concise_error
from hyops.runtime.paths import resolve_runtime_paths
from hyops.runtime.preflight_decision import (
    complete_preflight_decision,
    new_preflight_decision,
    validate_preflight_bypass,
)
from hyops.runtime.progress import ProgressDisplay, verbose_enabled
from hyops.runtime.root import require_runtime_selection
from hyops.runtime.source_roots import resolve_blueprints_root
from hyops.runtime.storage import format_runtime_storage_error, require_runtime_writable
from hyops.runtime.vault import VaultAuth, read_env

from .automation_access import (
    automation_session_paths,
    build_tunnel_ssh_argv,
    linux_tunnel_plan,
    load_automation_targets,
    local_route_conflicts,
    prepare_automation_session,
)
from .access_session import (
    LifecycleBusy,
    LifecycleLock,
    effective_status as effective_session_status,
    extend_session,
    format_utc,
    load_session,
    parse_utc,
    save_session,
    set_session_status,
    start_session,
    utc_now,
)
from .contracts import (
    enforce_step_contracts,
    explicit_step_inputs_changed,
    module_state_ok,
    module_state_status,
    resolved_step_inputs_file,
    step_state_ref,
)
from .iol_repair import (
    MODULE_REF as IOL_IMAGES_MODULE_REF,
)
from .iol_repair import (
    IolRepairError,
    parse_iol_mismatch,
    repair_iol_license,
)
from .planner import compute_preflight, run_step_module_command
from .schema import load_blueprint, resolve_blueprint_file, validate_blueprint


def _runtime_overlay_for_ref(ns, blueprint_ref: str) -> str:
    if not blueprint_ref:
        return ""
    if not (getattr(ns, "root", None) or getattr(ns, "env", None)):
        return ""

    paths = resolve_runtime_paths(getattr(ns, "root", None), getattr(ns, "env", None))
    overlay_root = (paths.config_dir / "blueprints").resolve()
    unresolved = overlay_root / _default_overlay_name(blueprint_ref)
    candidate = unresolved.resolve()
    try:
        candidate.relative_to(overlay_root)
    except ValueError as exc:
        raise ValueError(f"initialized blueprint resolves outside {overlay_root}: {unresolved}") from exc

    if unresolved.is_symlink() and not candidate.exists():
        raise FileNotFoundError(f"initialized blueprint link is broken: {unresolved}")
    if candidate.exists() and not candidate.is_file():
        raise ValueError(f"initialized blueprint is not a file: {candidate}")
    return str(candidate) if candidate.is_file() else ""


def _resolve_and_validate(
    ns,
    *,
    allow_runtime_overlay: bool = True,
) -> dict[str, Any]:
    blueprints_root = resolve_blueprints_root(getattr(ns, "blueprints_root", "blueprints"))
    blueprint_ref = str(getattr(ns, "ref", "") or "").strip()
    explicit_file = str(getattr(ns, "file", "") or "").strip()
    overlay_file = ""
    if allow_runtime_overlay and not explicit_file:
        overlay_file = _runtime_overlay_for_ref(ns, blueprint_ref)
    path = resolve_blueprint_file(
        ref=blueprint_ref,
        file_path=explicit_file or overlay_file,
        blueprints_root=blueprints_root,
    )
    spec = load_blueprint(path)
    payload = validate_blueprint(spec, path)
    if overlay_file and payload["blueprint_ref"] != blueprint_ref:
        raise ValueError(
            f"initialized blueprint ref mismatch: requested {blueprint_ref}, "
            f"file declares {payload['blueprint_ref']}: {path}"
        )
    return payload


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


def _editor_argv(ns) -> list[str]:
    explicit = str(getattr(ns, "editor", "") or "").strip()
    for candidate in (
        explicit,
        os.environ.get("HYOPS_EDITOR", "").strip(),
        os.environ.get("VISUAL", "").strip(),
        os.environ.get("EDITOR", "").strip(),
    ):
        if candidate:
            return shlex.split(candidate, posix=(os.name != "nt"))

    candidates = ["nano", "vim", "vi", "code --wait", "open -e", "notepad"]
    for candidate in candidates:
        argv = shlex.split(candidate, posix=(os.name != "nt"))
        if shutil.which(argv[0]):
            return argv

    raise RuntimeError("no editor command available. Set --editor or HYOPS_EDITOR.")


def _blueprint_file_for_edit(ns) -> Path:
    require_runtime_selection(
        getattr(ns, "root", None),
        getattr(ns, "env", None),
        command_label="hyops blueprint edit",
    )
    paths = resolve_runtime_paths(getattr(ns, "root", None), getattr(ns, "env", None))
    ensure_layout(paths)

    explicit = str(getattr(ns, "file", "") or "").strip()
    if explicit:
        _enforce_runtime_blueprint_file_scope(ns, paths, command_label="blueprint edit")
        explicit_path = Path(explicit).expanduser().resolve()
        if not explicit_path.exists():
            raise FileNotFoundError(f"blueprint file not found: {explicit_path}")
        if not explicit_path.is_file():
            raise ValueError(f"blueprint file is not a file: {explicit_path}")
        return explicit_path

    if not str(getattr(ns, "ref", "") or "").strip():
        raise ValueError(
            "blueprint edit requires --ref unless --file is set. "
            "Run blueprint init to generate a runtime blueprint first."
        )

    overlay = _runtime_overlay_for_ref(ns, str(getattr(ns, "ref", "")).strip())
    if not overlay:
        raise FileNotFoundError(
            f"initialized blueprint not found for {getattr(ns, 'ref', None)}; run `hyops blueprint init` first."
        )

    return Path(overlay)


def _resolve_edit_target(ns) -> Path:
    blueprint_file = _blueprint_file_for_edit(ns)
    if not blueprint_file.exists():
        raise FileNotFoundError(f"blueprint file not found: {blueprint_file}")
    if not blueprint_file.is_file():
        raise ValueError(f"blueprint file is not a regular file: {blueprint_file}")
    return blueprint_file


def _emit(payload: dict[str, Any], *, json_mode: bool) -> None:
    if json_mode:
        print(json.dumps(payload, indent=2, sort_keys=True))
        return

    print(f"blueprint={payload.get('blueprint_ref', '')} mode={payload.get('mode', '')} status=ok")
    print(f"path={payload.get('path', '')}")


def _cancelled_deploy_actions(ns, payload: dict[str, Any]) -> dict[str, str]:
    env_name = str(getattr(ns, "env", "") or "").strip()
    if env_name:
        selection = ["--env", env_name]
    else:
        selection = ["--root", str(getattr(ns, "root", "") or "")]

    blueprint_file = str(getattr(ns, "file", "") or "").strip()
    if blueprint_file:
        selector = ["--file", blueprint_file]
    else:
        selector = ["--ref", str(payload["blueprint_ref"])]

    return {
        "resume": shlex.join(["hyops", "blueprint", "deploy", *selection, *selector, "--execute"]),
        "destroy": shlex.join(["hyops", "blueprint", "destroy", *selection, *selector, "--execute"]),
    }


def _failed_deploy_has_resources(payload: dict[str, Any], paths) -> bool:
    for step in payload.get("steps") or []:
        status = module_state_status(paths.state_dir, step_state_ref(step))
        if status and status not in {"absent", "destroyed", "missing"}:
            return True
    return False


def _offer_failed_deploy_destroy(ns, payload: dict[str, Any], paths) -> int:
    if not _failed_deploy_has_resources(payload, paths):
        return 0

    destroy_command = _cancelled_deploy_actions(ns, payload)["destroy"]
    if not (sys.stdin.isatty() and sys.stdout.isatty()):
        print("WARN: deployment failed while resources may remain active")
        print(f"destroy incomplete environment: {destroy_command}")
        return 0

    print()
    print("deployment failed while resources may remain active")
    destroy_ns = argparse.Namespace(**vars(ns))
    destroy_ns.execute = True
    destroy_ns.yes = False
    destroy_ns.archive_before_destroy = False
    destroy_ns.skip_archive = False
    return run_destroy(destroy_ns)


def _image_archive_stem(value: str) -> str:
    stem = Path(value).name
    for suffix in (".tar.gz", ".qcow2", ".tgz", ".zip", ".img", ".bin", ".gz"):
        if stem.lower().endswith(suffix):
            stem = stem[: -len(suffix)]
            break
    if stem.lower().endswith("-clean"):
        stem = stem[:-6]
    return stem


def _eveng_image_display_name(value: str) -> str:
    stem = _image_archive_stem(value)
    lowered = stem.lower()

    if lowered.startswith("linux-alpine-"):
        return "Alpine Linux"
    if lowered == "linux-netem":
        return "NETem"
    if lowered.startswith("linux-tinycore-"):
        return "Tiny Core Linux"
    if lowered.startswith("linux-ubuntu-") and "server" in lowered:
        return "Ubuntu Server"
    return stem


def _configured_eveng_image_labels(step: dict[str, Any]) -> list[str]:
    if str(step.get("module_ref") or "") != "platform/linux/eve-ng-images":
        return []

    inputs = step.get("inputs")
    if not isinstance(inputs, dict):
        return []
    configured = inputs.get("eveng_images_list")
    if not isinstance(configured, list):
        return []

    labels: list[str] = []
    for entry in configured:
        if not isinstance(entry, dict):
            continue
        label = str(entry.get("label") or "").strip()
        if not label:
            source_name = str(entry.get("name") or entry.get("url") or "").strip()
            if source_name:
                label = _eveng_image_display_name(source_name)
        if label:
            labels.append(label)
    return labels


def _published_eveng_image_labels(
    step: dict[str, Any],
    outputs: dict[str, Any],
) -> list[str]:
    published = outputs.get("eveng_images_installed_names")
    if not isinstance(published, list):
        return []

    configured_labels: dict[str, str] = {}
    inputs = step.get("inputs")
    configured = inputs.get("eveng_images_list") if isinstance(inputs, dict) else None
    if isinstance(configured, list):
        for entry in configured:
            if not isinstance(entry, dict):
                continue
            name = Path(str(entry.get("name") or "").strip()).name
            label = str(entry.get("label") or "").strip()
            if name and label:
                configured_labels[name] = label

    labels: list[str] = []
    for value in published:
        name = Path(str(value).strip()).name
        if name:
            labels.append(configured_labels.get(name) or _eveng_image_display_name(name))
    return labels


def _step_presentation(
    step: dict[str, Any],
    *,
    state_dir: Path,
    progress_after: int,
) -> tuple[str, str, str]:
    presentation = step.get("presentation")
    if not isinstance(presentation, dict):
        presentation = {}

    label = str(presentation.get("label") or step["id"]).strip()
    details: list[str] = []
    success = str(presentation.get("success") or "").strip()
    if success:
        details.append(success)

    try:
        state = read_module_state(state_dir, step_state_ref(step))
    except (FileNotFoundError, OSError, ValueError):
        state = {}
    outputs = state.get("outputs")
    if not isinstance(outputs, dict):
        outputs = {}

    image_count = outputs.get("eveng_images_installed_count")
    if not isinstance(image_count, int):
        image_count = outputs.get("eveng_images_requested_count")
    if isinstance(image_count, int) and image_count >= 0:
        details.append(f"{image_count} images")

    health_status = str(outputs.get("eveng_health_status") or "").strip().lower()
    if health_status and health_status not in details:
        details.append(health_status)

    details.append(f"overall {progress_after}%")

    items = (
        _published_eveng_image_labels(step, outputs)
        or _configured_eveng_image_labels(step)
        or presentation.get("items")
    )
    item_line = ""
    if isinstance(items, list) and items:
        item_values = [str(item).strip() for item in items if str(item).strip()]
        if item_values:
            items_label = str(presentation.get("items_label") or "includes").strip()
            inline_items = f"  {items_label}: {', '.join(item_values)}"
            if len(item_values) > 4 or len(inline_items) > 100:
                item_line = "\n".join([f"  {items_label}:", *(f"    - {item}" for item in item_values)])
            else:
                item_line = inline_items

    return label, ", ".join(details), item_line


def _step_display_label(step: dict[str, Any]) -> str:
    presentation = step.get("presentation")
    if isinstance(presentation, dict):
        label = str(presentation.get("label") or "").strip()
        if label:
            return label

    step_id = str(step.get("id") or "").strip()
    words = [word for word in re.split(r"[_-]+", step_id) if word]
    names = {
        "api": "API",
        "cloudsql": "Cloud SQL",
        "config": "configuration",
        "day2": "Day 2",
        "dns": "DNS",
        "dr": "DR",
        "gcp": "GCP",
        "gke": "GKE",
        "gitops": "GitOps",
        "gns3": "GNS3",
        "gsm": "GSM",
        "ha": "HA",
        "healthcheck": "health checks",
        "iap": "IAP",
        "ip": "IP",
        "ipam": "IPAM",
        "kvm": "KVM",
        "netbox": "NetBox",
        "onprem": "on-premises",
        "ops": "operations",
        "pg": "PostgreSQL",
        "pgcore": "PostgreSQL core",
        "postgres": "PostgreSQL",
        "postgresql": "PostgreSQL",
        "powerdns": "PowerDNS",
        "repo": "repository",
        "rke2": "RKE2",
        "rocky9": "Rocky Linux 9",
        "sdn": "SDN",
        "sql": "SQL",
        "vm": "VM",
        "vms": "VMs",
        "vpn": "VPN",
        "vyos": "VyOS",
        "wan": "WAN",
    }
    rendered = [names.get(word.lower(), word.capitalize()) for word in words]

    for index in range(len(rendered) - 1):
        if rendered[index] == "Eve" and rendered[index + 1] == "Ng":
            rendered[index : index + 2] = ["EVE-NG"]
            break
    for index in range(len(rendered) - 2):
        if rendered[index : index + 3] == ["Ubuntu", "22", "04"]:
            rendered[index : index + 3] = ["Ubuntu 22.04"]
            break
    return " ".join(rendered) or step_id


def _destroy_preview_label(step: dict[str, Any], state_status: str) -> str:
    label = _step_display_label(step)
    if bool(step.get("retain_on_destroy", False)):
        return f"{label} (retained)"
    if state_status in {"absent", "destroyed", "missing"}:
        return f"{label} (already absent)"
    return label


def _destroy_gate_required(
    step: dict[str, Any],
    by_id: dict[str, dict[str, Any]],
    paths,
) -> bool:
    if not bool(step.get("destroy_gate", False)):
        return False
    for required_id in step.get("requires") or []:
        required_step = by_id.get(str(required_id))
        if required_step is None:
            continue
        status = module_state_status(
            paths.state_dir,
            step_state_ref(required_step),
        )
        if status and status not in {"absent", "destroyed", "missing"}:
            return True
    return False


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

    print(f"blueprint={payload['blueprint_ref']} mode={payload['mode']} plan_steps={len(payload['order'])}")
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


def _step_failure_state(step: dict[str, Any], paths) -> tuple[str, str, str]:
    try:
        state = read_module_state(paths.state_dir, step_state_ref(step))
    except (FileNotFoundError, OSError, ValueError):
        return "", "", ""
    return (
        str(state.get("run_id") or "").strip(),
        str(state.get("status") or "").strip().lower(),
        str(state.get("last_error") or "").strip(),
    )


def _new_step_failure_detail(
    step: dict[str, Any],
    paths,
    previous: tuple[str, str, str],
) -> str:
    current = _step_failure_state(step, paths)
    if current == previous or current[1] != "error" or not current[2]:
        return ""
    return concise_error(current[2])


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

        if not status or status in {"absent", "destroyed", "missing"}:
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


def _prompt_yes_no(prompt: str) -> bool | None:
    while True:
        try:
            answer = input(prompt)
        except (EOFError, KeyboardInterrupt):
            print()
            return None
        answer = re.sub(r"\x1b\[[0-?]*[ -/]*[@-~]", "", answer)
        answer = "".join(character for character in answer if character.isprintable())
        answer = answer.strip().casefold()
        if answer in {"y", "yes"}:
            return True
        if answer in {"", "n", "no"}:
            return False
        print("invalid response; enter y or n")


def _confirm_deploy_if_needed(ns, payload: dict[str, Any], paths) -> int:
    if bool(getattr(ns, "yes", False)):
        return 0
    if bool(getattr(ns, "json", False)):
        return 0

    signals = _collect_deploy_risk_signals(payload, paths)
    if not signals:
        return 0

    env_name = str(getattr(ns, "env", None) or getattr(paths.root, "name", "") or "").strip() or "default"
    count = len(signals)
    noun = "step" if count == 1 else "steps"
    print(f"WARN: deploy may change {count} active blueprint {noun} in env={env_name}.")
    print("steps:")
    for item in signals:
        step = next(
            candidate
            for candidate in payload.get("steps", [])
            if str(candidate.get("id") or "") == item["id"]
        )
        print(f"  - {_step_display_label(step)} (state={item['state_status']})")
        if verbose_enabled():
            print(
                f"    id={item['id']} action={item['action']} module={item['module_ref']} ref={item['state_ref']}"
            )

    if not (sys.stdin.isatty() and sys.stdout.isatty()):
        print("WARN: non-interactive session detected; proceeding without prompt (use --yes to silence).")
        return 0

    confirmed = _prompt_yes_no("Proceed with blueprint deploy? [y/N]: ")
    if confirmed is None:
        return CANCELLED
    if not confirmed:
        print("ERR: blueprint deploy cancelled by operator")
        return OPERATOR_ERROR
    return 0


def add_blueprint_subparser(sp: argparse._SubParsersAction) -> None:
    p = sp.add_parser("blueprint", help="Blueprint orchestration commands.")
    ssp = p.add_subparsers(dest="blueprint_cmd", required=True)

    def add_common_args(sub: argparse.ArgumentParser) -> None:
        sub.add_argument(
            "--ref",
            default="",
            help=(
                "Blueprint ref, e.g. onprem/eve-ng@v1. Uses the environment's "
                "initialized blueprint automatically when available."
            ),
        )
        sub.add_argument(
            "--file",
            default="",
            help="Explicit blueprint YAML path; overrides automatic environment selection.",
        )
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
    i.add_argument(
        "--root",
        default=None,
        help="Override runtime root for blueprint overlay output.",
    )
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
    i.add_argument(
        "--edit",
        action="store_true",
        help="Open the initialized blueprint in a local editor immediately.",
    )
    i.add_argument(
        "--editor",
        default="",
        help=(
            "Editor command to use when --edit is set. Defaults to HYOPS_EDITOR, VISUAL, EDITOR, then common editors."
        ),
    )
    i.set_defaults(_handler=run_init)

    e = ssp.add_parser(
        "edit",
        help="Open a runtime blueprint file in a local editor.",
    )
    add_common_args(e)
    e.add_argument("--root", default=None, help="Override runtime root for blueprint selection.")
    e.add_argument("--env", default=None, help="Runtime environment namespace.")
    e.add_argument(
        "--editor",
        default="",
        help=("Editor command to use. Defaults to HYOPS_EDITOR, VISUAL, EDITOR, then common editors."),
    )
    e.set_defaults(_handler=run_edit)

    q = ssp.add_parser("validate", help="Validate a blueprint manifest.")
    add_common_args(q)
    q.add_argument("--root", default=None, help="Override runtime root for overlay selection.")
    q.add_argument("--env", default=None, help="Runtime environment namespace.")
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
    r.add_argument("--root", default=None, help="Override runtime root for overlay selection.")
    r.add_argument("--env", default=None, help="Runtime environment namespace.")
    r.set_defaults(_handler=run_plan)

    a = ssp.add_parser("access", help="Open a declared private blueprint access path.")
    add_common_args(a)
    a.add_argument("--root", default=None, help="Override runtime root.")
    a.add_argument("--env", default=None, help="Runtime environment namespace.")
    a.add_argument(
        "--local-port",
        type=int,
        default=0,
        help="Local port (default: choose an available port).",
    )
    a.add_argument("--no-browser", action="store_true", help="Do not open the default browser.")
    a.add_argument(
        "--native-consoles",
        action="store_true",
        help="Forward active native console ports declared by the blueprint.",
    )
    a.add_argument(
        "--automation",
        action="store_true",
        help="Open private device automation access and write client configuration.",
    )
    a.add_argument(
        "--socks-port",
        type=int,
        default=0,
        help="Local device proxy port (default: choose an available port).",
    )
    a.add_argument(
        "--targets",
        default="",
        help="Override the environment automation target file.",
    )
    a.add_argument(
        "--route-lab",
        action="store_true",
        help="Route the declared management subnet through a Linux TUN interface.",
    )
    a.add_argument(
        "--session-minutes",
        type=int,
        default=0,
        help="Set a foreground-supervised access limit in minutes.",
    )
    a.add_argument(
        "--on-expiry",
        choices=("protected-release",),
        default="",
        help="Action authorised when the access-session limit expires.",
    )
    a.set_defaults(_handler=run_access)

    session = ssp.add_parser(
        "session",
        help="Inspect or change a time-bounded access session.",
    )
    session_commands = session.add_subparsers(dest="session_cmd", required=True)

    def add_session_args(sub: argparse.ArgumentParser) -> None:
        add_common_args(sub)
        sub.add_argument("--root", default=None, help="Override runtime root.")
        sub.add_argument("--env", default=None, help="Runtime environment namespace.")

    session_status = session_commands.add_parser(
        "status",
        help="Show the current access-session state.",
    )
    add_session_args(session_status)
    session_status.set_defaults(_handler=run_session)

    session_extend = session_commands.add_parser(
        "extend",
        help="Extend an active access-session deadline.",
    )
    add_session_args(session_extend)
    session_extend.add_argument(
        "--minutes",
        type=int,
        required=True,
        help="Minutes to add to the current deadline.",
    )
    session_extend.set_defaults(_handler=run_session)

    session_cancel = session_commands.add_parser(
        "cancel",
        help="Cancel the expiry action without closing access.",
    )
    add_session_args(session_cancel)
    session_cancel.set_defaults(_handler=run_session)

    device = ssp.add_parser(
        "device",
        help="Use devices through an active private blueprint access session.",
    )
    device_commands = device.add_subparsers(dest="device_cmd", required=True)

    def add_device_args(sub: argparse.ArgumentParser) -> None:
        add_common_args(sub)
        sub.add_argument("--root", default=None, help="Override runtime root.")
        sub.add_argument("--env", default=None, help="Runtime environment namespace.")

    device_list = device_commands.add_parser(
        "list",
        help="List discovered and operator-defined device targets.",
    )
    add_device_args(device_list)
    device_list.set_defaults(_handler=run_device)

    device_edit = device_commands.add_parser(
        "edit",
        help="Open the environment device targets in a local editor.",
    )
    add_device_args(device_edit)
    device_edit.add_argument(
        "--editor",
        default="",
        help=("Editor command to use. Defaults to HYOPS_EDITOR, VISUAL, EDITOR, then common editors."),
    )
    device_edit.set_defaults(_handler=run_device)

    device_ping = device_commands.add_parser(
        "ping",
        help="Test a device address through the managed lab gateway.",
    )
    add_device_args(device_ping)
    device_ping.add_argument("target", help="Device name or management IPv4 address.")
    device_ping.add_argument(
        "--count",
        type=int,
        default=3,
        help="Number of probes (default: 3).",
    )
    device_ping.set_defaults(_handler=run_device)

    device_ssh = device_commands.add_parser(
        "ssh",
        help="Open SSH to a device through the managed lab gateway.",
    )
    add_device_args(device_ssh)
    device_ssh.add_argument("target", help="Discovered or operator-defined device name.")
    device_ssh.set_defaults(_handler=run_device)

    device_web = device_commands.add_parser(
        "web",
        help="Open device web interfaces through the managed lab gateway.",
    )
    add_device_args(device_web)
    device_web.add_argument(
        "target",
        nargs="*",
        help="One or more device names or management IPv4 addresses.",
    )
    device_web.add_argument(
        "--all",
        dest="all_targets",
        action="store_true",
        help="Open every target that declares a web service.",
    )
    device_web.add_argument(
        "--scheme",
        choices=("http", "https"),
        default=None,
        help="Override the declared remote web scheme.",
    )
    device_web.add_argument(
        "--port",
        type=int,
        default=None,
        help="Override the declared remote web port.",
    )
    device_web.add_argument(
        "--path",
        default=None,
        help="Override the declared URL path.",
    )
    device_web.add_argument(
        "--local-port",
        type=int,
        default=0,
        help="Local loopback port (default: choose an available port).",
    )
    browser_mode = device_web.add_mutually_exclusive_group()
    browser_mode.add_argument(
        "--no-browser",
        action="store_true",
        help="Do not open the default browser.",
    )
    browser_mode.add_argument(
        "--open-all",
        action="store_true",
        help="Open every local URL when several targets are selected.",
    )
    device_web.set_defaults(_handler=run_device)

    device_shell = device_commands.add_parser(
        "shell",
        help="Open a shell configured for the active device session.",
    )
    add_device_args(device_shell)
    device_shell.set_defaults(_handler=run_device)

    device_run = device_commands.add_parser(
        "run",
        help="Run a command with the active device-session environment.",
    )
    add_device_args(device_run)
    device_run.add_argument(
        "command",
        nargs=argparse.REMAINDER,
        help="Command to run, normally after --.",
    )
    device_run.set_defaults(_handler=run_device)

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
    t.add_argument(
        "--out-dir",
        default=None,
        help="Override evidence root for executed module steps.",
    )
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
        help="Explicitly bypass the blueprint-level preflight gate.",
    )
    t.add_argument(
        "--preflight-bypass-reason",
        default=None,
        help="Required reason when --skip-preflight is used.",
    )
    t.add_argument(
        "--yes",
        action="store_true",
        help="Proceed without interactive confirmation when rerun/destructive risk signals are detected.",
    )
    restore_choice = t.add_mutually_exclusive_group()
    restore_choice.add_argument(
        "--restore-labs",
        action="store_true",
        help="Restore the latest verified lab archive declared by the blueprint.",
    )
    restore_choice.add_argument(
        "--skip-lab-restore",
        action="store_true",
        help="Deploy without restoring an available lab archive.",
    )
    t.add_argument(
        "--overwrite-labs",
        action="store_true",
        help="Allow --restore-labs to replace existing lab definitions.",
    )
    t.add_argument(
        "--overwrite-images",
        action="store_true",
        help="Allow --restore-labs to replace referenced base images.",
    )
    t.add_argument(
        "--repair-iol-license",
        action="store_true",
        help=(
            "On an exact IOL host-binding mismatch, retrieve one authorised "
            "repair from the configured broker, update the secret, and retry once."
        ),
    )
    t.add_argument(
        "--iol-repair-broker-url",
        default=None,
        help="HTTPS repair broker endpoint (or HYOPS_IOL_REPAIR_BROKER_URL).",
    )
    t.add_argument(
        "--iol-repair-public-key",
        default=None,
        help="PEM public key used to verify broker responses (or HYOPS_IOL_REPAIR_PUBLIC_KEY).",
    )
    t.add_argument(
        "--iol-repair-token-key",
        default="HYOPS_IOL_REPAIR_TOKEN",
        help="Shell/runtime-vault key containing the broker bearer token.",
    )
    t.add_argument(
        "--iol-repair-persist",
        choices=["vault", "gsm"],
        default=None,
        help="Also persist the repaired secret to HashiCorp Vault or GCP Secret Manager.",
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
    d.add_argument(
        "--out-dir",
        default=None,
        help="Override evidence root for executed module steps.",
    )
    d.add_argument(
        "--yes",
        action="store_true",
        help="Proceed without interactive confirmation.",
    )
    archive_choice = d.add_mutually_exclusive_group()
    archive_choice.add_argument(
        "--archive-before-destroy",
        action="store_true",
        help="Export and verify declared lab data before teardown.",
    )
    archive_choice.add_argument(
        "--skip-archive",
        action="store_true",
        help="Destroy without exporting declared lab data.",
    )
    d.add_argument(
        "--guest-quiesced",
        action="store_true",
        help=(
            "Confirm stateful EVE-NG guests were shut down inside the guest "
            "before node-state capture."
        ),
    )
    d.set_defaults(_handler=run_destroy)

    b = ssp.add_parser(
        "rebuild",
        help="Destroy blueprint resources, then deploy them again in dependency order.",
    )
    add_common_args(b)
    b.add_argument(
        "--execute",
        action="store_true",
        help="Execute reverse destruction followed by ordered deployment.",
    )
    b.add_argument("--root", default=None, help="Override runtime root.")
    b.add_argument("--env", default=None, help="Runtime environment namespace.")
    b.add_argument(
        "--module-root",
        default="modules",
        help="Module root directory for step execution.",
    )
    b.add_argument("--out-dir", default=None, help="Override run-record root for module steps.")
    b.add_argument(
        "--deps-inputs-dir",
        default=None,
        help="Optional dependency inputs directory for deploy steps.",
    )
    b.add_argument(
        "--deps-force",
        action="store_true",
        help="Force dependency applies during deployment.",
    )
    b.add_argument(
        "--skip-preflight",
        action="store_true",
        help="Explicitly bypass deploy preflight after teardown.",
    )
    b.add_argument(
        "--preflight-bypass-reason",
        default=None,
        help="Required reason when --skip-preflight is used.",
    )
    b.add_argument(
        "--yes",
        action="store_true",
        help="Proceed without interactive confirmation.",
    )
    b.set_defaults(_handler=run_rebuild)


def run_validate(ns) -> int:
    try:
        payload = _resolve_and_validate(ns)
        _emit(payload, json_mode=bool(getattr(ns, "json", False)))
        return 0
    except Exception as exc:
        print(f"ERR: blueprint validation failed: {exc}")
        return OPERATOR_ERROR


def _resolve_device_blueprint(ns, paths) -> dict[str, Any]:
    if str(getattr(ns, "ref", "") or "").strip() or str(getattr(ns, "file", "") or "").strip():
        return _resolve_and_validate(ns)

    candidates: list[dict[str, Any]] = []
    blueprint_dir = Path(paths.config_dir) / "blueprints"
    for path in sorted(blueprint_dir.glob("*.yml")):
        try:
            payload = validate_blueprint(load_blueprint(path), path)
        except (OSError, ValueError):
            continue
        access = payload.get("access") if isinstance(payload.get("access"), dict) else {}
        if isinstance(access.get("automation"), dict) and access["automation"]:
            candidates.append(payload)
    if not candidates:
        raise ValueError("no initialized automation blueprint was found; pass --ref or run blueprint init")
    if len(candidates) > 1:
        refs = ", ".join(str(item.get("blueprint_ref") or "") for item in candidates)
        raise ValueError(f"multiple automation blueprints are initialized ({refs}); pass --ref")
    return candidates[0]


def _device_material(ns) -> tuple[dict[str, Any], dict[str, Any]]:
    require_runtime_selection(
        getattr(ns, "root", None),
        getattr(ns, "env", None),
        command_label="hyops blueprint device",
    )
    paths = resolve_runtime_paths(getattr(ns, "root", None), getattr(ns, "env", None))
    payload = _resolve_device_blueprint(ns, paths)
    access = payload.get("access") if isinstance(payload.get("access"), dict) else {}
    automation = access.get("automation") if isinstance(access.get("automation"), dict) else {}
    if not automation:
        raise ValueError("blueprint does not declare device automation access")
    env_name = str(getattr(ns, "env", "") or Path(paths.root).name)
    material = automation_session_paths(
        paths=paths,
        blueprint_ref=str(payload.get("blueprint_ref") or "blueprint"),
        env_name=env_name,
    )
    return automation, material


def _device_context(ns) -> tuple[dict[str, Any], dict[str, Any], list[dict[str, Any]]]:
    automation, material = _device_material(ns)
    target_file = material["target_file"]
    if not target_file.is_file():
        raise ValueError("device targets are unavailable; run blueprint access with --automation")
    targets = load_automation_targets(target_file, automation["management_cidr"])
    return automation, material, targets


def _device_edit_command(ns) -> str:
    command = ["hyops", "blueprint", "device", "edit"]
    env_name = str(getattr(ns, "env", "") or "").strip()
    blueprint_ref = str(getattr(ns, "ref", "") or "").strip()
    if env_name:
        command.extend(["--env", env_name])
    if blueprint_ref:
        command.extend(["--ref", blueprint_ref])
    return shlex.join(command)


def _resolve_device_target(
    value: str,
    automation: dict[str, Any],
    targets: list[dict[str, Any]],
) -> tuple[str, dict[str, Any] | None]:
    token = str(value or "").strip()
    for target in targets:
        if token in {target["name"], target["host"]}:
            return str(target["host"]), target
    try:
        address = ipaddress.ip_address(token)
    except ValueError as exc:
        raise ValueError(f"unknown device target: {token}") from exc
    network = ipaddress.ip_network(automation["management_cidr"], strict=False)
    if address not in network:
        raise ValueError(f"device address {address} is outside {network}")
    return str(address), None


def _device_web_requests(
    ns,
    automation: dict[str, Any],
    targets: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    raw_targets = getattr(ns, "target", []) or []
    if isinstance(raw_targets, str):
        target_tokens = [raw_targets]
    else:
        target_tokens = [str(item) for item in raw_targets]
    target_tokens = [item.strip() for item in target_tokens if item.strip()]
    use_all = bool(getattr(ns, "all_targets", False))
    if use_all and target_tokens:
        raise ValueError("device web accepts target names or --all, not both")
    if use_all:
        selected = [
            (str(target["host"]), target) for target in targets if isinstance(target.get("web"), dict)
        ]
        if not selected:
            raise ValueError("no targets declare web access; run device edit and add a web mapping")
    else:
        if not target_tokens:
            raise ValueError("device web requires at least one target or --all")
        selected = [_resolve_device_target(token, automation, targets) for token in target_tokens]

    scheme_override = str(getattr(ns, "scheme", None) or "").strip().lower()
    if scheme_override and scheme_override not in {"http", "https"}:
        raise ValueError("--scheme must be http or https")
    port_override = int(getattr(ns, "port", None) or 0)
    if port_override and not 1 <= port_override <= 65535:
        raise ValueError("--port must be between 1 and 65535")
    path_override = getattr(ns, "path", None)
    if path_override is not None:
        path_override = str(path_override or "/")
        if not path_override.startswith("/") or path_override.startswith("//"):
            raise ValueError("--path must begin with one /")

    requests: list[dict[str, Any]] = []
    seen_addresses: set[str] = set()
    for address, target in selected:
        if address in seen_addresses:
            raise ValueError(f"device web target is duplicated: {address}")
        seen_addresses.add(address)
        declared = target.get("web") if target else None
        web = declared if isinstance(declared, dict) else {}
        scheme = scheme_override or str(web.get("scheme") or "https")
        remote_port = port_override or int(web.get("port") or (443 if scheme == "https" else 80))
        path = str(path_override if path_override is not None else web.get("path") or "/")
        requests.append(
            {
                "address": address,
                "label": str(target["name"] if target else address),
                "scheme": scheme,
                "remote_port": remote_port,
                "path": path,
            }
        )
    return requests


def _run_device_web(
    ns,
    *,
    ssh: str,
    ssh_config: Path,
    gateway_alias: str,
    automation: dict[str, Any],
    targets: list[dict[str, Any]],
) -> int:
    requests = _device_web_requests(ns, automation, targets)
    requested_local_port = int(getattr(ns, "local_port", 0) or 0)
    if requested_local_port and len(requests) > 1:
        raise ValueError("--local-port is available only with one device web target")

    sessions: list[dict[str, Any]] = []
    try:
        for request in requests:
            local_port = _available_local_port(requested_local_port)
            _require_local_ports_available([local_port])
            argv = [
                ssh,
                "-F",
                str(ssh_config),
                "-N",
                "-o",
                "ExitOnForwardFailure=yes",
                "-L",
                (f"127.0.0.1:{local_port}:{request['address']}:{request['remote_port']}"),
                gateway_alias,
            ]
            proc = subprocess.Popen(
                argv,
                cwd=str(Path.home()),
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
                text=True,
            )
            try:
                _wait_for_local_port(local_port, proc)
            except Exception:
                _stop_process(proc)
                raise
            local_url = f"{request['scheme']}://127.0.0.1:{local_port}{request['path']}"
            target_url = (
                f"{request['scheme']}://{request['address']}:{request['remote_port']}{request['path']}"
            )
            sessions.append(
                {
                    "label": request["label"],
                    "local_url": local_url,
                    "target_url": target_url,
                    "proc": proc,
                }
            )

        if len(sessions) == 1:
            session = sessions[0]
            print(f"device web access: {session['label']}")
            print(f"local URL: {session['local_url']}")
            print(f"target: {session['target_url']}")
        else:
            print(f"device web access: {len(sessions)} targets")
            for session in sessions:
                print(f"- {session['label']}  local={session['local_url']}  target={session['target_url']}")
        print("press Ctrl-C to close access")

        open_all = bool(getattr(ns, "open_all", False))
        no_browser = bool(getattr(ns, "no_browser", False))
        if len(sessions) > 1 and not no_browser and not open_all:
            print("browser: not opened; use --open-all to open every URL")
        if not no_browser and (len(sessions) == 1 or open_all):
            for session in sessions:
                open_operator_url(str(session["local_url"]))

        while True:
            for session in sessions:
                proc = session["proc"]
                return_code = proc.poll()
                if return_code is None:
                    continue
                detail = (proc.stderr.read() if proc.stderr else "").strip()
                raise ValueError(
                    detail or f"device web tunnel for {session['label']} exited with rc={return_code}"
                )
            time.sleep(0.25)
    except KeyboardInterrupt:
        print("device web access closed")
        return 0
    finally:
        for session in reversed(sessions):
            _stop_process(session["proc"])


def _device_process_environment(material: dict[str, Any]) -> dict[str, str]:
    required = {
        "SSH configuration": Path(material["ssh_config"]),
        "Ansible configuration": Path(material["ansible_config"]),
        "Nornir host inventory": Path(material["nornir_hosts"]),
        "Nornir group inventory": Path(material["nornir_groups"]),
        "Nornir defaults": Path(material["nornir_defaults"]),
        "session metadata": Path(material["session_file"]),
    }
    for label, path in required.items():
        if not path.is_file():
            raise ValueError(f"{label} is unavailable; run blueprint access with --automation")
    try:
        session = yaml.safe_load(Path(material["session_file"]).read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError) as exc:
        raise ValueError("device session metadata is invalid") from exc
    proxy = str(session.get("socks_proxy") or "").strip()
    inventory_options = {
        "host_file": str(material["nornir_hosts"]),
        "group_file": str(material["nornir_groups"]),
        "defaults_file": str(material["nornir_defaults"]),
    }
    environment = dict(os.environ)
    environment.update(
        {
            "ANSIBLE_CONFIG": str(material["ansible_config"]),
            "HYOPS_DEVICE_INVENTORY": str(material["inventory"]),
            "HYOPS_DEVICE_TARGETS": str(material["target_file"]),
            "HYOPS_DEVICE_SSH_CONFIG": str(material["ssh_config"]),
            "HYOPS_DEVICE_PROXY": proxy,
            "NORNIR_INVENTORY_PLUGIN": "SimpleInventory",
            "NORNIR_INVENTORY_OPTIONS": json.dumps(inventory_options),
            "NORNIR_SSH_CONFIG_FILE": str(material["ssh_config"]),
        }
    )
    if proxy:
        environment["ALL_PROXY"] = proxy
        environment["all_proxy"] = proxy
    return environment


def run_device(ns) -> int:
    try:
        action = str(getattr(ns, "device_cmd", "") or "")
        if action == "edit":
            automation, material = _device_material(ns)
            target_file = Path(material["target_file"])
            if not target_file.is_file():
                raise ValueError("device targets are unavailable; run blueprint access with --automation")
            editor_argv = _editor_argv(ns)
            editor_argv.append(str(target_file))
            print(f"Opening device targets for edit: {target_file}")
            result = subprocess.run(editor_argv, check=False)
            if result.returncode != 0:
                raise ValueError(f"editor returned {result.returncode}")
            load_automation_targets(target_file, automation["management_cidr"])
            return 0

        automation, material, targets = _device_context(ns)
        if action == "list":
            if bool(getattr(ns, "json", False)):
                print(json.dumps({"targets": targets}, indent=2, sort_keys=True))
            elif not targets:
                print(
                    f"no devices discovered; connect a management interface to {automation['management_network_label']}"
                )
            else:
                for target in targets:
                    source = "DHCP" if target.get("source") == "dhcp-lease" else "static"
                    platform = target.get("platform") or "unspecified"
                    user = str(target["user"])
                    if source == "DHCP" and user == automation["default_user"]:
                        user += " (default)"
                    web = target.get("web")
                    web_summary = ""
                    if isinstance(web, dict):
                        web_summary = f"  web={web['scheme']}:{web['port']}"
                    print(
                        f"{target['name']}  {target['host']}  user={user}  "
                        f"port={target['port']}  {platform}  {source}{web_summary}"
                    )
            return 0

        ssh_config = Path(material["ssh_config"])
        if not ssh_config.is_file():
            raise ValueError(
                "private access is not active; run blueprint access with --automation and keep it open"
            )
        ssh = shutil.which("ssh")
        if not ssh:
            raise ValueError("ssh is required; run: hyops setup base")

        if action == "ping":
            count = int(getattr(ns, "count", 3) or 3)
            if not 1 <= count <= 20:
                raise ValueError("--count must be between 1 and 20")
            address, _target = _resolve_device_target(ns.target, automation, targets)
            result = subprocess.run(
                [
                    ssh,
                    "-F",
                    str(ssh_config),
                    str(material["gateway_alias"]),
                    "ping",
                    "-c",
                    str(count),
                    "--",
                    address,
                ],
                cwd=str(Path.home()),
                check=False,
            )
            return int(result.returncode)

        if action == "ssh":
            _address, target = _resolve_device_target(ns.target, automation, targets)
            if target is None:
                raise ValueError("device SSH requires a named target; run device list")
            alias = f"{material['alias_prefix']}-{target['name']}"
            ssh_argv = [
                ssh,
                "-F",
                str(ssh_config),
                "-l",
                str(target["user"]),
                "-p",
                str(target["port"]),
            ]
            if target["identity_file"]:
                ssh_argv.extend(["-i", str(target["identity_file"])])
            ssh_argv.append(alias)
            result = subprocess.run(
                ssh_argv,
                cwd=str(Path.home()),
                check=False,
            )
            if result.returncode == 255:
                print(f"ERR: device SSH failed for {target['name']} as {target['user']}.")
                print(f"device targets: {material['target_file']}")
                print(f"edit: {_device_edit_command(ns)}")
            return int(result.returncode)
        if action == "web":
            return _run_device_web(
                ns,
                ssh=ssh,
                ssh_config=ssh_config,
                gateway_alias=str(material["gateway_alias"]),
                automation=automation,
                targets=targets,
            )
        if action in {"shell", "run"}:
            environment = _device_process_environment(material)
            if action == "shell":
                shell = str(os.environ.get("SHELL") or shutil.which("bash") or "").strip()
                if not shell:
                    raise ValueError("an interactive shell is unavailable")
                print("device automation environment ready; exit to leave")
                result = subprocess.run(
                    [shell, "-i"],
                    cwd=str(Path.cwd()),
                    env=environment,
                    check=False,
                )
                return int(result.returncode)
            command = list(getattr(ns, "command", []) or [])
            if command and command[0] == "--":
                command = command[1:]
            if not command:
                raise ValueError("device run requires a command after --")
            result = subprocess.run(
                command,
                cwd=str(Path.cwd()),
                env=environment,
                check=False,
            )
            return int(result.returncode)
        raise ValueError(f"unsupported device command: {action}")
    except Exception as exc:
        print(f"ERR: blueprint device failed: {exc}")
        return OPERATOR_ERROR


def run_init(ns) -> int:
    try:
        require_runtime_selection(
            getattr(ns, "root", None),
            getattr(ns, "env", None),
            command_label="hyops blueprint init",
        )
        payload = _resolve_and_validate(ns, allow_runtime_overlay=False)
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
                f"initialized blueprint already exists: {dest_path} (use --force to overwrite)"
            )
        shutil.copy2(Path(payload["path"]), dest_path)
        dest_path.chmod(0o600)
        if bool(getattr(ns, "edit", False)):
            editor_argv = _editor_argv(ns)
            editor_argv.append(str(dest_path))
            print(f"Opening blueprint for edit: {dest_path}")
            result = subprocess.run(editor_argv, check=False)
            if result.returncode != 0:
                raise RuntimeError(f"editor returned {result.returncode}")
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
            print(f"file={dest_path}")
        return 0
    except Exception as exc:
        print(f"ERR: blueprint init failed: {exc}")
        return OPERATOR_ERROR


def run_edit(ns) -> int:
    try:
        blueprint_file = _resolve_edit_target(ns)
        editor_argv = _editor_argv(ns)
        editor_argv.append(str(blueprint_file))
        print(f"Opening blueprint for edit: {blueprint_file}")
        result = subprocess.run(editor_argv, check=False)
        if result.returncode != 0:
            print(f"ERR: blueprint edit failed: editor returned {result.returncode}")
            return OPERATOR_ERROR
        return 0
    except Exception as exc:
        print(f"ERR: blueprint edit failed: {exc}")
        return OPERATOR_ERROR


def run_preflight(ns) -> int:
    try:
        payload = _resolve_and_validate(ns)
    except Exception as exc:
        print(f"ERR: blueprint preflight failed: {format_runtime_storage_error(exc)}")
        return OPERATOR_ERROR

    try:
        require_runtime_selection(
            getattr(ns, "root", None),
            getattr(ns, "env", None),
            command_label="hyops blueprint preflight",
        )
        paths = resolve_runtime_paths(getattr(ns, "root", None), getattr(ns, "env", None))
        ensure_layout(paths)
        require_runtime_writable(paths.root)
        _enforce_runtime_blueprint_file_scope(
            ns,
            paths,
            command_label="hyops blueprint preflight",
        )
    except Exception as exc:
        print(f"ERR: blueprint preflight failed: {format_runtime_storage_error(exc)}")
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
            print(f"  - {item['id']}: {item['status']} {item['action']} {item['module_ref']}")
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


def _available_local_port(requested: int) -> int:
    if requested:
        if not 1 <= requested <= 65535:
            raise ValueError("--local-port must be between 1 and 65535")
        return requested
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _wait_for_local_port(port: int, proc: subprocess.Popen, timeout_s: float = 15.0) -> None:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            raise RuntimeError(f"SSH tunnel exited with rc={proc.returncode}")
        probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            probe.bind(("127.0.0.1", port))
        except OSError as exc:
            if exc.errno in {errno.EADDRINUSE, 48, 98}:
                return
        finally:
            probe.close()
        time.sleep(0.25)
    raise TimeoutError("timed out waiting for the local SSH tunnel")


def _parse_eve_qemu_console_ports(output: str) -> list[int]:
    ports: set[int] = set()
    for line in str(output or "").splitlines():
        if "qemu-system-" not in line:
            continue
        for raw in re.findall(r"(?:\*|\[[^]]+\]|[0-9a-fA-F:.]+):(\d+)\b", line):
            port = int(raw)
            if 1 <= port <= 65535:
                ports.add(port)
    return sorted(ports)


def _require_local_ports_available(ports: list[int]) -> None:
    sockets: list[socket.socket] = []
    try:
        for port in ports:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            try:
                sock.bind(("127.0.0.1", port))
            except OSError:
                sock.close()
                raise
            sockets.append(sock)
    except OSError as exc:
        raise ValueError(f"local port {port} is unavailable on localhost: {exc}") from exc
    finally:
        for sock in sockets:
            sock.close()


def _native_console_status(ports: list[int], *, mode: str = "eve-ng-qemu") -> str:
    if ports:
        return "native console ports: " + ", ".join(str(item) for item in ports)
    if mode == "gns3-api":
        return "native consoles: waiting for GNS3 nodes"
    return "native consoles: waiting for active QEMU nodes"


def _discover_eve_qemu_console_ports(
    ssh_base: list[str],
    ssh_target: str,
    known_hosts_file: Path,
) -> list[int]:
    probe = subprocess.run(
        [*ssh_base, ssh_target, "sudo -n ss -H -lntp"],
        cwd=str(Path.home()),
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=20,
        check=False,
    )
    if probe.returncode != 0:
        raise ValueError(
            "failed to discover native EVE-NG consoles: " + _ssh_access_error(probe.stderr, known_hosts_file)
        )
    return _parse_eve_qemu_console_ports(probe.stdout)


def _native_console_refresher(
    *,
    ssh_base: list[str],
    ssh_target: str,
    known_hosts_file: Path,
    forwarded_ports: list[int],
) -> tuple[Callable[[], None], Callable[[], None]]:
    forwarded = set(forwarded_ports)
    processes: dict[int, subprocess.Popen] = {}
    failed: set[int] = set()

    def refresh() -> None:
        active = _discover_eve_qemu_console_ports(
            ssh_base,
            ssh_target,
            known_hosts_file,
        )
        for port in active:
            if port in forwarded:
                continue
            proc: subprocess.Popen | None = None
            try:
                _require_local_ports_available([port])
                argv = [*ssh_base, "-N", "-o", "ExitOnForwardFailure=yes"]
                argv.extend(["-L", f"127.0.0.1:{port}:127.0.0.1:{port}"])
                argv.append(ssh_target)
                proc = subprocess.Popen(argv, cwd=str(Path.home()))
                _wait_for_local_port(port, proc, timeout_s=10)
            except Exception as exc:
                _stop_process(proc)
                if port not in failed:
                    print(
                        f"WARN: native console port {port} could not be forwarded: {exc}",
                        flush=True,
                    )
                    failed.add(port)
                continue
            processes[port] = proc
            forwarded.add(port)
            failed.discard(port)
            print(f"native console available: vnc://127.0.0.1:{port}", flush=True)

    def stop() -> None:
        for proc in processes.values():
            _stop_process(proc)
        processes.clear()

    return refresh, stop


def _runtime_access_secret(paths, env_name: str, env_key: str) -> str:
    value = str(os.environ.get(env_key) or "").strip()
    if value:
        return value
    vault_file = paths.vault_dir / "bootstrap.vault.env"
    try:
        values = read_env(vault_file, VaultAuth())
    except (OSError, RuntimeError, subprocess.SubprocessError, ValueError) as exc:
        raise ValueError(
            f"native console credential {env_key} could not be read from the environment vault"
        ) from exc
    value = str(values.get(env_key) or "").strip()
    if not value:
        raise ValueError(
            f"native console credential {env_key} is missing; run: hyops secrets ensure --env {env_name} {env_key}"
        )
    return value


def _gns3_api_json(url: str, username: str, password: str) -> Any:
    token = base64.b64encode(f"{username}:{password}".encode()).decode("ascii")
    request = urllib.request.Request(
        url,
        headers={
            "Accept": "application/json",
            "Authorization": f"Basic {token}",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=5) as response:
            return json.load(response)
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        raise ValueError("GNS3 console discovery API request failed") from exc


def _discover_gns3_consoles(
    local_api_port: int,
    username: str,
    password: str,
) -> list[tuple[int, str, str]]:
    root = f"http://127.0.0.1:{local_api_port}/v2"
    projects = _gns3_api_json(f"{root}/projects", username, password)
    if not isinstance(projects, list):
        raise ValueError("GNS3 projects response is invalid")
    consoles: dict[int, tuple[int, str, str]] = {}
    local_hosts = {"127.0.0.1", "localhost", "0.0.0.0", "::", "::1"}
    for project in projects:
        if not isinstance(project, dict):
            continue
        project_id = str(project.get("project_id") or "").strip()
        if not project_id:
            continue
        encoded_id = urllib.parse.quote(project_id, safe="")
        nodes = _gns3_api_json(
            f"{root}/projects/{encoded_id}/nodes",
            username,
            password,
        )
        if not isinstance(nodes, list):
            continue
        for node in nodes:
            if not isinstance(node, dict):
                continue
            host = str(node.get("console_host") or "").strip().lower()
            console_type = str(node.get("console_type") or "").strip().lower()
            raw_port = node.get("console")
            if host not in local_hosts or console_type in {"", "none"}:
                continue
            if not isinstance(raw_port, int) or not 1 <= raw_port <= 65535:
                continue
            name = str(node.get("name") or node.get("node_id") or "node").strip()
            consoles[raw_port] = (raw_port, console_type, name)
    return [consoles[port] for port in sorted(consoles)]


def _gns3_console_refresher(
    *,
    ssh_base: list[str],
    ssh_target: str,
    local_api_port: int,
    username: str,
    password: str,
) -> tuple[Callable[[], None], Callable[[], None]]:
    forwarded: set[int] = set()
    processes: dict[int, subprocess.Popen] = {}
    failed: set[int] = set()

    def refresh() -> None:
        for port, console_type, name in _discover_gns3_consoles(
            local_api_port,
            username,
            password,
        ):
            if port in forwarded:
                continue
            proc: subprocess.Popen | None = None
            try:
                _require_local_ports_available([port])
                argv = [*ssh_base, "-N", "-o", "ExitOnForwardFailure=yes"]
                argv.extend(["-L", f"127.0.0.1:{port}:127.0.0.1:{port}"])
                argv.append(ssh_target)
                proc = subprocess.Popen(argv, cwd=str(Path.home()))
                _wait_for_local_port(port, proc, timeout_s=10)
            except (OSError, RuntimeError, TimeoutError, ValueError) as exc:
                _stop_process(proc)
                if port not in failed:
                    print(
                        f"WARN: {name} console port {port} could not be forwarded: {exc}",
                        flush=True,
                    )
                    failed.add(port)
                continue
            processes[port] = proc
            forwarded.add(port)
            failed.discard(port)
            scheme = "spice" if console_type.startswith("spice") else console_type
            print(
                f"native console available: {name} ({console_type}) {scheme}://127.0.0.1:{port}",
                flush=True,
            )

    def stop() -> None:
        for proc in processes.values():
            _stop_process(proc)
        processes.clear()

    return refresh, stop


def _print_native_console_client_guidance(mode: str) -> None:
    if mode == "gns3-api":
        print("GNS3 node consoles are forwarded to their matching local ports.")
        return
    if is_windows_wsl():
        print("Windows native consoles require the EVE-NG Windows Client Pack.")
        print("HTML5 consoles remain available without it.")


def _native_console_mode(access: dict[str, Any], enabled: bool) -> str:
    if not enabled:
        return ""
    mode = str(access.get("native_console_mode") or "").strip()
    if mode not in {"eve-ng-qemu", "gns3-api"}:
        raise ValueError("blueprint does not declare supported native console access")
    return mode


def _extract_access_host(outputs: dict[str, Any]) -> str:
    def valid_ipv4(value: Any) -> str:
        token = str(value or "").strip().split("/", 1)[0]
        try:
            address = ipaddress.ip_address(token)
        except ValueError:
            return ""
        if not isinstance(address, ipaddress.IPv4Address):
            return ""
        if address.is_unspecified or address.is_loopback or address.is_link_local:
            return ""
        return str(address)

    def first_ipv4(value: Any) -> str:
        if isinstance(value, dict):
            for item in value.values():
                found = first_ipv4(item)
                if found:
                    return found
            return ""
        if isinstance(value, (list, tuple)):
            for item in value:
                found = first_ipv4(item)
                if found:
                    return found
            return ""
        return valid_ipv4(value)

    vms = outputs.get("vms")
    if isinstance(vms, dict):
        for item in vms.values():
            if not isinstance(item, dict):
                continue
            for key in ("ipv4_address", "private_ipv4", "ipv4_addresses"):
                found = first_ipv4(item.get(key))
                if found:
                    return found

    for key in ("ipv4_addresses_all", "ipv4_addresses", "ipv4_configured_primary"):
        found = first_ipv4(outputs.get(key))
        if found:
            return found

    if isinstance(vms, dict):
        for item in vms.values():
            if not isinstance(item, dict):
                continue
            found = first_ipv4(item.get("ipv4_configured_primary"))
            if found:
                return found
    return ""


def _print_guest_network_guidance(access: dict[str, Any]) -> None:
    guest_network = str(access.get("guest_network_label") or "").strip()
    if not guest_network:
        return
    print(f"guest egress network: {guest_network}")
    print(f"guest gateway and DNS: {access.get('guest_gateway')}")
    print(f"guest DHCP range: {access.get('guest_dhcp_range')}")
    print(f"guest setup: connect a node interface to {guest_network} and use DHCP")


def _state_age(updated_at: Any) -> str:
    raw = str(updated_at or "").strip()
    if not raw:
        return "unknown"
    try:
        recorded = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        if recorded.tzinfo is None:
            recorded = recorded.replace(tzinfo=timezone.utc)
        seconds = max(0, int((datetime.now(timezone.utc) - recorded).total_seconds()))
    except ValueError:
        return "unknown"
    return _duration_text(seconds)


def _duration_text(seconds: int) -> str:
    minutes = max(0, int(seconds)) // 60
    hours, remaining_minutes = divmod(minutes, 60)
    days, remaining_hours = divmod(hours, 24)
    if days:
        return f"{days}d {remaining_hours}h"
    if hours:
        return f"{hours}h {remaining_minutes}m"
    return f"{minutes}m"


def _state_age_seconds(updated_at: Any) -> int:
    raw = str(updated_at or "").strip()
    if not raw:
        return 0
    try:
        recorded = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        if recorded.tzinfo is None:
            recorded = recorded.replace(tzinfo=timezone.utc)
    except ValueError:
        return 0
    return max(0, int((datetime.now(timezone.utc) - recorded).total_seconds()))


def _print_cost_estimate(
    estimate: CostEstimate,
    *,
    state: dict[str, Any],
    access_seconds: int | None = None,
) -> None:
    if not estimate.available:
        print("estimated fixed cost: unavailable")
        return
    print(f"estimated fixed cost: {format_money(estimate.hourly, estimate.currency)}/hour")
    state_seconds = _state_age_seconds(state.get("updated_at"))
    if state_seconds:
        print(
            "estimated maximum since resource update: "
            f"{format_money(estimate.amount_for_seconds(state_seconds), estimate.currency)}"
        )
    if access_seconds is not None:
        print(
            "estimated access-session cost: "
            f"{format_money(estimate.amount_for_seconds(access_seconds), estimate.currency)}"
        )
    if estimate.basis:
        print(f"pricing basis: {estimate.basis}")


def _gcp_cost_estimate_with_progress(
    *,
    project_id: str,
    zone: str,
    state: dict[str, Any],
    paths,
) -> CostEstimate:
    progress = ProgressDisplay(show_elapsed=False)
    progress.start(
        "cloud-cost",
        "Estimating cloud cost",
        plain="estimating cloud cost",
    )
    try:
        estimate = estimate_gcp_vm_cost(
            project_id=project_id,
            zone=zone,
            state=state,
            cache_dir=paths.meta_dir / "pricing",
        )
    except Exception:
        estimate = CostEstimate(
            False,
            detail="cloud pricing could not be resolved",
        )
    except KeyboardInterrupt:
        progress.finish(
            "cloud-cost",
            "Cloud cost estimate",
            "cancelled",
            plain="cloud cost estimate: cancelled",
        )
        raise
    progress.finish(
        "cloud-cost",
        "Cloud cost estimate",
        "ok" if estimate.available else "skipped",
        plain=("cloud cost estimate: ready" if estimate.available else "cloud cost estimate: unavailable"),
    )
    return estimate


def _gcp_blueprint_cost_estimate(
    payload: dict[str, Any],
    paths,
) -> CostEstimate | None:
    context = _gcp_blueprint_cost_context(payload, paths)
    if context is None:
        return None
    state, project_id, zone = context
    return _gcp_cost_estimate_with_progress(
        project_id=project_id,
        zone=zone,
        state=state,
        paths=paths,
    )


def _gcp_blueprint_cost_context(
    payload: dict[str, Any],
    paths,
) -> tuple[dict[str, Any], str, str] | None:
    if not str(payload.get("blueprint_ref") or "").startswith("gcp/"):
        return None
    access = payload.get("access")
    if not isinstance(access, dict):
        return None
    state_ref = str(access.get("state_ref") or "").strip()
    if not state_ref:
        return None
    try:
        module_ref, state_instance = split_module_state_ref(state_ref)
        state = read_module_state(
            paths.state_dir,
            module_ref,
            state_instance=state_instance,
        )
    except (OSError, ValueError):
        return None
    outputs = state.get("outputs") if isinstance(state.get("outputs"), dict) else {}
    vms = outputs.get("vms") if isinstance(outputs.get("vms"), dict) else {}
    if not vms:
        return None
    first_vm = next(iter(vms.values()))
    if not isinstance(first_vm, dict):
        return None
    vm_id = str(first_vm.get("vm_id") or "").strip()
    match = re.fullmatch(r"projects/([^/]+)/zones/([^/]+)/instances/([^/]+)", vm_id)
    if not match:
        return None
    project_id, zone, _instance = match.groups()
    return state, project_id, zone


def _destroy_lifecycle_snapshot(
    payload: dict[str, Any],
    paths,
    *,
    estimate: CostEstimate | None = None,
    observed_at: datetime | None = None,
) -> dict[str, Any] | None:
    context = _gcp_blueprint_cost_context(payload, paths)
    if context is None:
        return None
    state, _project_id, _zone = context
    observed = observed_at or datetime.now(timezone.utc)
    started = gcp_vm_lifecycle_started_at(state)
    if started is None:
        raw_updated = str(state.get("updated_at") or "").strip()
        try:
            started = datetime.fromisoformat(raw_updated.replace("Z", "+00:00"))
        except ValueError:
            started = None
        if started is not None and started.tzinfo is None:
            started = started.replace(tzinfo=timezone.utc)
    if started is not None:
        started = started.astimezone(timezone.utc)
        duration_seconds: int | None = max(
            0,
            int((observed - started).total_seconds()),
        )
    else:
        duration_seconds = None
    resolved_estimate = estimate
    if resolved_estimate is None:
        resolved_estimate = _gcp_blueprint_cost_estimate(payload, paths)
    estimate_available = bool(isinstance(resolved_estimate, CostEstimate) and resolved_estimate.available)
    return {
        "provider": "gcp",
        "resource_generation_started_at": (started.isoformat().replace("+00:00", "Z") if started else None),
        "observed_at": observed.isoformat().replace("+00:00", "Z"),
        "duration_seconds": duration_seconds,
        "estimate": {
            "available": estimate_available,
            "currency": (resolved_estimate.currency if estimate_available else "USD"),
            "fixed_hourly": (str(resolved_estimate.hourly) if estimate_available else None),
            "fixed_total": (
                str(resolved_estimate.amount_for_seconds(duration_seconds))
                if estimate_available and duration_seconds is not None
                else None
            ),
            "basis": (resolved_estimate.basis if estimate_available else "unavailable"),
            "classification": ("public list-price estimate; not a GCP invoice or billing total"),
        },
    }


def _complete_destroy_lifecycle(
    snapshot: dict[str, Any] | None,
    *,
    archive: str,
    resources: str,
) -> dict[str, Any] | None:
    if snapshot is None:
        return None
    lifecycle = dict(snapshot)
    lifecycle["archive"] = archive
    lifecycle["resources"] = resources
    estimate = dict(lifecycle["estimate"])
    if resources == "released":
        estimate["ongoing_hourly"] = "0.00"
        lifecycle["released_at"] = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    elif resources == "retained" and estimate["available"]:
        estimate["ongoing_hourly"] = estimate["fixed_hourly"]
    else:
        estimate["ongoing_hourly"] = None
    lifecycle["estimate"] = estimate
    return lifecycle


def _print_destroy_lifecycle_summary(lifecycle: dict[str, Any] | None) -> None:
    if lifecycle is None:
        return
    resources = str(lifecycle.get("resources") or "unverified")
    if resources == "retained":
        duration_label = "resource duration so far"
        cost_label = "estimated fixed cost so far"
    elif resources == "released":
        duration_label = "resource duration at release"
        cost_label = "estimated fixed cost before release"
    else:
        duration_label = "resource duration at teardown attempt"
        cost_label = "estimated fixed cost at teardown attempt"
    duration_seconds = lifecycle.get("duration_seconds")
    if isinstance(duration_seconds, int):
        print(f"{duration_label}: {_duration_text(duration_seconds)}")
    else:
        print(f"{duration_label}: unavailable")
    estimate = lifecycle["estimate"]
    currency = str(estimate["currency"])
    fixed_total = estimate.get("fixed_total")
    if fixed_total is None:
        print(f"{cost_label}: unavailable")
    else:
        print(f"{cost_label}: {format_money(Decimal(str(fixed_total)), currency)}")
    ongoing = estimate.get("ongoing_hourly")
    if ongoing is None:
        print("estimated ongoing rate: unverified")
    else:
        print(f"estimated ongoing rate: {format_money(Decimal(str(ongoing)), currency)}/hour")
    if estimate.get("basis") and estimate["basis"] != "unavailable":
        print(f"pricing basis: {estimate['basis']}")
    print("estimate only; not a GCP invoice or billing total")


def _offer_access_close_destroy(
    ns,
    payload: dict[str, Any],
    state: dict[str, Any],
    *,
    project_id: str = "",
    cost_estimate: CostEstimate | None = None,
    access_started_at: float | None = None,
) -> int:
    access = payload.get("access") if isinstance(payload.get("access"), dict) else {}
    if not bool(access.get("offer_destroy_on_close", False)):
        return 0

    env_name = str(getattr(ns, "env", None) or "default").strip() or "default"
    print()
    print(f"environment: {env_name}")
    if project_id:
        print(f"GCP project: {project_id}")
        validated, enabled, _detail = diagnose_project_billing(project_id)
        if validated:
            print(f"billing: {'enabled' if enabled else 'disabled'}")
        else:
            print("billing: unable to verify")
        print(
            f"trial, credit and spend details: https://console.cloud.google.com/billing?project={project_id}"
        )
    print(f"resource state age: {_state_age(state.get('updated_at'))}")
    if cost_estimate is not None:
        access_seconds = (
            max(0, int(time.monotonic() - access_started_at)) if access_started_at is not None else None
        )
        _print_cost_estimate(
            cost_estimate,
            state=state,
            access_seconds=access_seconds,
        )
    print("billable resources may remain active after access closes")

    destroy_command = (
        f"hyops blueprint destroy --env {env_name} --ref {payload.get('blueprint_ref', '')} --execute"
    )
    if not (sys.stdin.isatty() and sys.stdout.isatty()):
        print(f"destroy when finished: {destroy_command}")
        return 0

    destroy_ns = argparse.Namespace(**vars(ns))
    destroy_ns.execute = True
    destroy_ns.yes = False
    destroy_ns.archive_before_destroy = False
    destroy_ns.skip_archive = False
    destroy_ns._cost_estimate = cost_estimate
    return run_destroy(destroy_ns)


def _expire_access_session(
    ns,
    payload: dict[str, Any],
    paths,
    session_record: dict[str, Any],
    *,
    cost_estimate: CostEstimate | None = None,
) -> int:
    print("access session expired; preserving declared state before teardown")
    try:
        with LifecycleLock(paths, "access-session protected release"):
            current = load_session(paths, str(payload["blueprint_ref"]))
            if current is None or str(current.get("session_id") or "") != str(
                session_record.get("session_id") or ""
            ):
                raise ValueError("access-session authority record changed before expiry")
            if str(current.get("status") or "") != "active":
                raise ValueError(
                    f"access-session expiry is not authorised in state {current.get('status', 'unknown')}"
                )
            access = payload.get("access")
            state_ref = str((access if isinstance(access, dict) else {}).get("state_ref") or "")
            module_ref, state_instance = split_module_state_ref(state_ref)
            state = read_module_state(
                paths.state_dir,
                module_ref,
                state_instance=state_instance,
            )
            generation = _access_resource_generation(payload, state)
            if generation != str(current.get("resource_generation") or ""):
                set_session_status(
                    paths,
                    current,
                    "stale-generation",
                    reason="resource generation changed before expiry",
                )
                print("ERR: access-session generation changed; environment retained")
                return OPERATOR_ERROR

            current["status"] = "executing"
            current["executing_at"] = format_utc(utc_now())
            save_session(paths, current)
            destroy_ns = argparse.Namespace(**vars(ns))
            destroy_ns.execute = True
            destroy_ns.yes = True
            destroy_ns.archive_before_destroy = bool(payload.get("archive_before_destroy"))
            destroy_ns.skip_archive = False
            destroy_ns._cost_estimate = cost_estimate
            destroy_ns._lifecycle_lock_held = True
            rc = run_destroy(destroy_ns)
            current["status"] = "released" if rc == 0 else "retained-after-failure"
            current["outcome"] = {
                "destroy_rc": int(rc),
                "resources_released": rc == 0,
            }
            if rc != 0:
                current["outcome"]["reason"] = "protected lifecycle did not complete"
            current["completed_at"] = format_utc(utc_now())
            save_session(paths, current)
    except LifecycleBusy as exc:
        print(f"ERR: protected release did not start: {exc}")
        print("review the active lifecycle operation before releasing the environment")
        return OPERATOR_ERROR
    except Exception as exc:
        try:
            current = load_session(paths, str(payload["blueprint_ref"]))
            if current is not None and str(current.get("session_id") or "") == str(
                session_record.get("session_id") or ""
            ):
                set_session_status(
                    paths,
                    current,
                    "retained-after-failure",
                    reason=str(exc),
                )
        except (OSError, ValueError):
            pass
        print(f"ERR: protected release did not complete: {exc}")
        print("environment retained")
        return OPERATOR_ERROR
    if rc != 0:
        print("ERR: scheduled teardown did not complete; review the session run record")
    return rc


def _close_access_session(
    paths,
    session_record: dict[str, Any] | None,
    status: str,
    *,
    reason: str = "",
) -> None:
    if session_record is None:
        return
    try:
        with LifecycleLock(paths, f"access-session {status}"):
            current = load_session(paths, str(session_record["blueprint_ref"]))
            if current is None or str(current.get("session_id") or "") != str(
                session_record.get("session_id") or ""
            ):
                return
            if str(current.get("status") or "") != "active":
                return
            set_session_status(paths, current, status, reason=reason)
    except (LifecycleBusy, OSError, ValueError):
        return


def _current_access_generation(payload: dict[str, Any], paths) -> str:
    access = payload.get("access") if isinstance(payload.get("access"), dict) else {}
    state_ref = str(access.get("state_ref") or "").strip()
    module_ref, state_instance = split_module_state_ref(state_ref)
    state = read_module_state(
        paths.state_dir,
        module_ref,
        state_instance=state_instance,
    )
    return _access_resource_generation(payload, state)


def _session_output(record: dict[str, Any]) -> dict[str, Any]:
    output = dict(record)
    output["effective_status"] = effective_session_status(record)
    return output


def _print_session(output: dict[str, Any]) -> None:
    print(f"session={output.get('session_id', '')}")
    print(f"status={output.get('effective_status', output.get('status', 'unknown'))}")
    print(f"blueprint={output.get('blueprint_ref', '')}")
    print(f"deadline={output.get('deadline_at', '')}")
    print(f"expiry_action={output.get('expiry_action', '')}")
    outcome = output.get("outcome")
    if isinstance(outcome, dict) and outcome:
        if "resources_released" in outcome:
            print(f"resources_released={'yes' if bool(outcome['resources_released']) else 'no'}")
        if outcome.get("reason"):
            print(f"reason={outcome['reason']}")
    print(f"run record: {output.get('run_record', '')}")


def run_session(ns) -> int:
    try:
        payload = _resolve_and_validate(ns)
        require_runtime_selection(
            ns.root,
            getattr(ns, "env", None),
            command_label="hyops blueprint session",
        )
        paths = resolve_runtime_paths(ns.root, getattr(ns, "env", None))
        blueprint_ref = str(payload["blueprint_ref"])
        record = load_session(paths, blueprint_ref)
        if record is None:
            raise ValueError("no access-session record exists for this blueprint")

        command = str(getattr(ns, "session_cmd", "") or "")
        if command == "status":
            output = _session_output(record)
        else:
            with LifecycleLock(paths, f"access-session {command}"):
                record = load_session(paths, blueprint_ref)
                if record is None:
                    raise ValueError("access-session record disappeared")
                if command == "extend":
                    minutes = int(getattr(ns, "minutes", 0) or 0)
                    if minutes < 1 or minutes > 7 * 24 * 60:
                        raise ValueError("--minutes must be between 1 and 10080")
                    if effective_session_status(record) != "active":
                        raise ValueError("only a supervised active session can be extended")
                    if _current_access_generation(payload, paths) != str(
                        record.get("resource_generation") or ""
                    ):
                        set_session_status(
                            paths,
                            record,
                            "stale-generation",
                            reason="resource generation changed before extension",
                        )
                        raise ValueError("resource generation changed; session not extended")
                    extend_session(paths, record, seconds=minutes * 60)
                elif command == "cancel":
                    if str(record.get("status") or "") != "active":
                        raise ValueError("only an active session can be cancelled")
                    set_session_status(
                        paths,
                        record,
                        "cancelled",
                        reason="expiry cancelled by operator",
                    )
                else:
                    raise ValueError(f"unsupported session command: {command}")
                output = _session_output(record)
        if bool(getattr(ns, "json", False)):
            print(json.dumps(output, indent=2, sort_keys=True))
        else:
            _print_session(output)
        return 0
    except (LifecycleBusy, OSError, ValueError) as exc:
        print(f"ERR: blueprint session failed: {exc}")
        return OPERATOR_ERROR


def _destroyed_blueprint_cost_cleared(payload: dict[str, Any], paths) -> bool:
    """Return true only when every declared step has terminal resource state."""

    for step in payload.get("steps") or []:
        if bool(step.get("retain_on_destroy", False)):
            return False
        status = module_state_status(paths.state_dir, step_state_ref(step))
        if status not in {"destroyed", "absent"}:
            return False
    return True


def _access_known_hosts_file(paths, state_ref: str, state: dict[str, Any]) -> Path:
    run_id = str(state.get("run_id") or "current").strip() or "current"
    scope = re.sub(r"[^A-Za-z0-9_.-]+", "_", f"{state_ref}-{run_id}").strip("._")
    directory = (Path(paths.meta_dir) / "access_known_hosts").resolve()
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    try:
        directory.chmod(0o700)
    except OSError:
        pass
    return directory / f"{scope}.known_hosts"


def _ssh_access_trust_options(
    known_hosts_file: Path,
    *,
    host_key_alias: str = "",
) -> list[str]:
    options = [
        "-o",
        "StrictHostKeyChecking=accept-new",
        "-o",
        f"UserKnownHostsFile={known_hosts_file}",
        "-o",
        "LogLevel=ERROR",
    ]
    if host_key_alias:
        options.extend(["-o", f"HostKeyAlias={host_key_alias}"])
    return options


def _ssh_access_error(stderr: str, known_hosts_file: Path) -> str:
    detail = str(stderr or "").strip()
    if "REMOTE HOST IDENTIFICATION HAS CHANGED" in detail or "Host key verification failed" in detail:
        return (
            "SSH host identity changed unexpectedly for the current VM state; access was stopped. "
            f"Review the deployed VM and its scoped trust record: {known_hosts_file}. "
            "If the VM was intentionally rebuilt, rerun the blueprint deploy so access uses the new VM state."
        )
    return detail or "SSH connection failed"


def _stop_process(proc: subprocess.Popen | None) -> None:
    if proc is None or proc.poll() is not None:
        return
    proc.terminate()
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait(timeout=5)


def _automation_settings(access: dict[str, Any], ns) -> dict[str, Any] | None:
    requested = bool(getattr(ns, "automation", False) or getattr(ns, "route_lab", False))
    if not requested:
        return None
    automation = access.get("automation")
    if not isinstance(automation, dict) or not automation:
        raise ValueError("blueprint does not declare device automation access")
    return automation


def _read_automation_leases(
    ssh_base: list[str],
    ssh_target: str,
    automation: dict[str, Any],
) -> str:
    if automation.get("discovery_mode") == "containerlab-inspect":
        result = subprocess.run(
            [
                *ssh_base,
                ssh_target,
                "sudo -n containerlab inspect --all -f json",
            ],
            cwd=str(Path.home()),
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            timeout=20,
            check=False,
        )
        return result.stdout if result.returncode == 0 else ""
    lease_file = str(automation.get("lease_file") or "").strip()
    if not lease_file:
        return ""
    remote_command = (
        f"cat -- {shlex.quote(lease_file)} 2>/dev/null || sudo -n cat -- {shlex.quote(lease_file)}"
    )
    result = subprocess.run(
        [*ssh_base, ssh_target, remote_command],
        cwd=str(Path.home()),
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        timeout=20,
        check=False,
    )
    return result.stdout if result.returncode == 0 else ""


def _prepare_automation_access(
    *,
    ns,
    payload: dict[str, Any],
    paths,
    automation: dict[str, Any],
    gateway: dict[str, Any],
    ssh_base: list[str],
    ssh_target: str,
    reserved_ports: list[int] | None = None,
) -> tuple[int, dict[str, Any]]:
    requested_port = int(getattr(ns, "socks_port", 0) or 0) or int(automation.get("local_socks_port") or 0)
    socks_port = _available_local_port(requested_port)
    reserved = set(reserved_ports or [])
    if socks_port in reserved and requested_port:
        raise ValueError(f"device proxy port {socks_port} is already used by this access session")
    while socks_port in reserved:
        socks_port = _available_local_port(0)
    _require_local_ports_available([socks_port])
    lease_text = _read_automation_leases(ssh_base, ssh_target, automation)
    session = prepare_automation_session(
        paths=paths,
        blueprint_ref=str(payload.get("blueprint_ref") or "blueprint"),
        env_name=str(getattr(ns, "env", "") or Path(paths.root).name),
        automation=automation,
        gateway=gateway,
        socks_port=socks_port,
        lease_text=lease_text,
        discovery_text=lease_text,
        target_file_override=str(getattr(ns, "targets", "") or ""),
    )
    return socks_port, session


def _automation_refresher(
    *,
    ns,
    payload: dict[str, Any],
    paths,
    automation: dict[str, Any],
    gateway: dict[str, Any],
    ssh_base: list[str],
    ssh_target: str,
    socks_port: int,
    session: dict[str, Any],
) -> Callable[[], None] | None:
    if str(getattr(ns, "targets", "") or ""):
        return None

    def refresh() -> None:
        lease_text = _read_automation_leases(ssh_base, ssh_target, automation)
        if not lease_text:
            return
        updated = prepare_automation_session(
            paths=paths,
            blueprint_ref=str(payload.get("blueprint_ref") or "blueprint"),
            env_name=str(getattr(ns, "env", "") or Path(paths.root).name),
            automation=automation,
            gateway=gateway,
            socks_port=socks_port,
            lease_text=lease_text,
            discovery_text=lease_text,
        )
        added = list(updated.get("new_targets") or [])
        session.clear()
        session.update(updated)
        for name in added:
            target = next(
                (item for item in updated["targets"] if item["name"] == name),
                None,
            )
            if target:
                print(f"device discovered: {name} ({target['host']})", flush=True)

    return refresh


def _print_automation_access(
    automation: dict[str, Any],
    session: dict[str, Any],
    *,
    route_requested: bool = False,
) -> None:
    print(f"automation network: {automation['management_network_label']} ({automation['management_cidr']})")
    if automation.get("discovery_mode") == "containerlab-inspect":
        print("device discovery: reading Containerlab runtime state")
    else:
        print("device discovery: watching management-network DHCP leases")
    print("device commands: hyops blueprint device --help")
    if verbose_enabled():
        print(f"device proxy: {session['socks_proxy']}")
        print(f"static target overrides: {session['target_file']}")
        print(f"SSH and VS Code config: {session['ssh_config']}")
        print(f"automation inventory: {session['inventory']}")
        print(f"API proxy settings: {session['proxy_env']}")
    if not route_requested:
        print("direct routing: not active; use device commands or the API proxy")
    if session["discovered_count"]:
        print(f"management addresses discovered: {session['discovered_count']}")
    if session["aliases"]:
        print(f"SSH targets: {', '.join(session['aliases'])}")
    else:
        print(
            "device targets: none discovered; connect a management interface to "
            f"{automation['management_network_label']}"
        )


def _print_lab_route_ready(automation: dict[str, Any]) -> None:
    print(f"local route: {automation['management_cidr']} through the lab host")
    if is_windows_wsl():
        print(
            "route scope: HybridOps Linux environment; Windows applications use the generated proxy or SSH config"
        )


def _start_lab_route(
    automation: dict[str, Any],
    gateway: dict[str, Any],
    *,
    scope: str,
) -> tuple[subprocess.Popen, dict[str, Any]]:
    if not sys.platform.startswith("linux"):
        raise ValueError(
            "--route-lab currently requires Linux; use --automation for portable SSH and API access"
        )
    conflicts = local_route_conflicts(automation["management_cidr"])
    if conflicts:
        raise ValueError("management subnet conflicts with a local route: " + conflicts[0])
    ip_command = shutil.which("ip")
    if not ip_command:
        raise ValueError("--route-lab requires the ip command")
    if not Path("/dev/net/tun").exists():
        raise ValueError("--route-lab requires Linux TUN support at /dev/net/tun")
    plan = linux_tunnel_plan(scope)
    if Path(f"/sys/class/net/{plan['interface']}").exists():
        raise ValueError(f"local tunnel interface is already in use: {plan['interface']}")
    privilege: list[str] = []
    if os.geteuid() != 0:
        sudo = shutil.which("sudo")
        if not sudo:
            raise ValueError("--route-lab requires sudo to create a local route")
        privilege = [sudo]

    def run_ip(*arguments: str, check: bool = True) -> subprocess.CompletedProcess:
        result = subprocess.run(
            [*privilege, ip_command, *arguments],
            cwd=str(Path.home()),
            text=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE if check else subprocess.DEVNULL,
            check=False,
        )
        if check and result.returncode != 0:
            detail = str(result.stderr or "").strip().splitlines()
            reason = detail[-1] if detail else f"ip exited with rc={result.returncode}"
            raise ValueError(f"local route setup failed: {reason}")
        return result

    route_proc: subprocess.Popen | None = None
    try:
        run_ip(
            "tuntap",
            "add",
            "dev",
            plan["interface"],
            "mode",
            "tun",
            "user",
            str(os.getuid()),
        )
        run_ip(
            "address",
            "replace",
            plan["local_cidr"],
            "peer",
            plan["remote_ip"],
            "dev",
            plan["interface"],
        )
        run_ip("link", "set", plan["interface"], "up")
        route_proc = subprocess.Popen(
            build_tunnel_ssh_argv(
                gateway=gateway,
                plan=plan,
                remote_helper="/usr/local/sbin/hybridops-lab-route",
            ),
            cwd=str(Path.home()),
        )
        ping = shutil.which("ping")
        if not ping:
            raise ValueError("--route-lab requires ping to verify the tunnel")
        deadline = time.monotonic() + 12
        while time.monotonic() < deadline:
            if route_proc.poll() is not None:
                raise ValueError(f"lab route exited with rc={route_proc.returncode}")
            probe = subprocess.run(
                [ping, "-c", "1", "-W", "1", plan["remote_ip"]],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
            )
            if probe.returncode == 0:
                break
            time.sleep(0.5)
        else:
            raise ValueError("timed out verifying the private lab route")
        run_ip(
            "route",
            "replace",
            automation["management_cidr"],
            "via",
            plan["remote_ip"],
            "dev",
            plan["interface"],
        )
        gateway_probe = subprocess.run(
            [ping, "-c", "1", "-W", "2", automation["management_gateway"]],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
        if gateway_probe.returncode != 0:
            raise ValueError("private management gateway did not respond through the lab route")
        plan["privilege"] = privilege
        plan["ip_command"] = ip_command
        return route_proc, plan
    except BaseException:
        _stop_process(route_proc)
        run_ip("link", "delete", plan["interface"], check=False)
        raise


def _stop_lab_route(
    route_proc: subprocess.Popen | None,
    route_plan: dict[str, Any] | None,
) -> None:
    _stop_process(route_proc)
    if not route_plan:
        return
    ip_command = str(route_plan.get("ip_command") or "")
    if not ip_command:
        return
    privilege = [str(item) for item in route_plan.get("privilege") or []]
    subprocess.run(
        [*privilege, ip_command, "link", "delete", route_plan["interface"]],
        cwd=str(Path.home()),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )


def _wait_for_access_processes(
    access_proc: subprocess.Popen,
    route_proc: subprocess.Popen | None = None,
    maintenance: Callable[[], None] | None = None,
) -> int:
    next_maintenance = time.monotonic() + 3
    while True:
        access_rc = access_proc.poll()
        if access_rc is not None:
            return int(access_rc)
        if route_proc is not None:
            route_rc = route_proc.poll()
            if route_rc is not None:
                return int(route_rc)
        if maintenance is not None and time.monotonic() >= next_maintenance:
            try:
                maintenance()
            except Exception as exc:
                if verbose_enabled():
                    print(f"WARN: device discovery refresh failed: {exc}")
            next_maintenance = time.monotonic() + 8
        time.sleep(0.5)


def _session_options(ns, payload: dict[str, Any]) -> tuple[int, str]:
    minutes = int(getattr(ns, "session_minutes", 0) or 0)
    if minutes < 0 or minutes > 7 * 24 * 60:
        raise ValueError("--session-minutes must be between 0 and 10080")
    action = str(getattr(ns, "on_expiry", "") or "").strip()
    if minutes == 0 and action:
        raise ValueError("--on-expiry requires --session-minutes")
    if minutes > 0 and not action:
        raise ValueError("--session-minutes requires --on-expiry protected-release")
    if minutes == 0:
        return 0, ""
    if str(payload.get("blueprint_ref") or "") not in {
        "gcp/eve-ng@v1",
        "gcp/gns3@v1",
        "gcp/containerlab@v1",
    }:
        raise ValueError(
            "time-bounded access is supported for the GCP EVE-NG, GNS3, and Containerlab blueprints"
        )
    return minutes * 60, action


def _access_resource_generation(
    payload: dict[str, Any],
    state: dict[str, Any],
) -> str:
    access = payload.get("access") if isinstance(payload.get("access"), dict) else {}
    outputs = state.get("outputs") if isinstance(state.get("outputs"), dict) else {}
    vms = outputs.get("vms") if isinstance(outputs.get("vms"), dict) else {}
    identities: dict[str, dict[str, str]] = {}
    for name, raw in sorted(vms.items()):
        vm = raw if isinstance(raw, dict) else {}
        identities[str(name)] = {key: str(vm.get(key) or "") for key in ("vm_id", "vm_name", "zone")}
    material = {
        "blueprint_ref": str(payload.get("blueprint_ref") or ""),
        "state_ref": str(access.get("state_ref") or ""),
        "state_run_id": str(state.get("run_id") or ""),
        "state_updated_at": str(state.get("updated_at") or ""),
        "vms": identities,
    }
    encoded = json.dumps(material, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def _session_warning_seconds(duration_seconds: int) -> tuple[int, ...]:
    return tuple(threshold for threshold in (1800, 600, 300, 60) if threshold < duration_seconds)


def _wait_for_managed_access(
    access_proc: subprocess.Popen,
    route_proc: subprocess.Popen | None,
    *,
    maintenance: Callable[[], None] | None,
    paths,
    session_record: dict[str, Any] | None,
) -> int | None:
    if session_record is None:
        return _wait_for_access_processes(
            access_proc,
            route_proc,
            maintenance=maintenance,
        )

    session_id = str(session_record["session_id"])
    duration_seconds = int(session_record["duration_seconds"])
    warned: set[tuple[str, int]] = set()
    next_maintenance = time.monotonic() + 3
    while True:
        access_rc = access_proc.poll()
        if access_rc is not None:
            return int(access_rc)
        if route_proc is not None:
            route_rc = route_proc.poll()
            if route_rc is not None:
                return int(route_rc)

        current = load_session(paths, str(session_record["blueprint_ref"]))
        if current is None or str(current.get("session_id") or "") != session_id:
            print("session supervision replaced; access remains open without expiry")
            return _wait_for_access_processes(
                access_proc,
                route_proc,
                maintenance=maintenance,
            )
        session_record.clear()
        session_record.update(current)
        status = str(session_record.get("status") or "")
        if status == "cancelled":
            print("session expiry cancelled; access remains open")
            return _wait_for_access_processes(
                access_proc,
                route_proc,
                maintenance=maintenance,
            )
        if status != "active":
            return _wait_for_access_processes(
                access_proc,
                route_proc,
                maintenance=maintenance,
            )

        deadline = parse_utc(str(session_record["deadline_at"]))
        now = utc_now()
        remaining = (deadline - now).total_seconds()
        if remaining <= 0:
            print("access session limit reached")
            return None
        deadline_key = str(session_record["deadline_at"])
        for threshold in _session_warning_seconds(duration_seconds):
            warning = (deadline_key, threshold)
            if remaining <= threshold and warning not in warned:
                print(f"session expires in {threshold // 60} minutes")
                warned.add(warning)

        if maintenance is not None and time.monotonic() >= next_maintenance:
            try:
                maintenance()
            except Exception as exc:
                if verbose_enabled():
                    print(f"WARN: device discovery refresh failed: {exc}")
            next_maintenance = time.monotonic() + 8
        time.sleep(0.5)


def _combine_maintenance(
    *callbacks: Callable[[], None] | None,
) -> Callable[[], None] | None:
    active = tuple(callback for callback in callbacks if callback is not None)
    if not active:
        return None

    def run() -> None:
        first_error: Exception | None = None
        for callback in active:
            try:
                callback()
            except Exception as exc:
                if first_error is None:
                    first_error = exc
        if first_error is not None:
            raise first_error

    return run


def run_access(ns) -> int:
    native_console_stop: Callable[[], None] | None = None
    session_record: dict[str, Any] | None = None
    paths = None
    try:
        payload = _resolve_and_validate(ns)
        session_seconds, expiry_action = _session_options(ns, payload)
        access = payload.get("access") if isinstance(payload.get("access"), dict) else {}
        if not access:
            raise ValueError("blueprint does not declare an access path")
        require_runtime_selection(ns.root, getattr(ns, "env", None), command_label="hyops blueprint access")
        paths = resolve_runtime_paths(ns.root, getattr(ns, "env", None))
        state_ref = str(access.get("state_ref") or "").strip()
        module_ref, state_instance = split_module_state_ref(state_ref)
        state = read_module_state(paths.state_dir, module_ref, state_instance=state_instance)
        if session_seconds:
            env_name = str(getattr(ns, "env", None) or paths.root.name).strip()
            with LifecycleLock(paths, "start access session"):
                session_record = start_session(
                    paths,
                    env_name=env_name,
                    blueprint_ref=str(payload["blueprint_ref"]),
                    state_ref=state_ref,
                    resource_generation=_access_resource_generation(payload, state),
                    duration_seconds=session_seconds,
                    expiry_action=expiry_action,
                )
            print(f"session deadline: {session_record['deadline_at']}")
            print(f"expiry action: {session_record['expiry_action']}")
            print(f"session run record: {session_record['run_record']}")
        outputs = state.get("outputs") if isinstance(state.get("outputs"), dict) else {}
        vms = outputs.get("vms") if isinstance(outputs.get("vms"), dict) else {}
        if not vms:
            raise ValueError(f"VM outputs are unavailable in state {state_ref}")
        vm = next(iter(vms.values()))
        if not isinstance(vm, dict):
            raise ValueError(f"VM output is invalid in state {state_ref}")
        access_type = str(access.get("type") or "").strip()
        remote_port = int(access.get("remote_port") or 80)
        path = str(access.get("path") or "/")
        automation = _automation_settings(access, ns)

        if access_type in {"direct-http", "ssh-forward", "ssh-tcp-forward"}:
            host = _extract_access_host(outputs)
            if not host:
                raise ValueError(f"VM state does not contain a usable IPv4 address: {state_ref}")
            if access_type == "direct-http":
                if automation:
                    raise ValueError("device automation access requires an SSH-forward access path")
                url = f"http://{host}:{remote_port}{path}"
                print("opening direct EVE-NG access")
                print(f"URL: {url}")
                _print_guest_network_guidance(access)
                if not bool(getattr(ns, "no_browser", False)):
                    open_operator_url(url)
                return 0

            ssh = shutil.which("ssh")
            if not ssh:
                raise ValueError("ssh is required; run: hyops setup base")
            ssh_user = str(access.get("ssh_user") or "").strip()
            ssh_key = Path(str(access.get("ssh_key_file") or "")).expanduser().resolve()
            if not ssh_key.exists():
                raise ValueError(f"declared SSH key does not exist: {ssh_key}")
            ssh_target = f"{ssh_user}@{host}"
            known_hosts_file = _access_known_hosts_file(paths, state_ref, state)
            ssh_base = [
                ssh,
                "-o",
                "BatchMode=yes",
                "-o",
                "IdentitiesOnly=yes",
                *_ssh_access_trust_options(known_hosts_file),
                "-i",
                str(ssh_key),
            ]
            identity_check = subprocess.run(
                [*ssh_base, ssh_target, "true"],
                cwd=str(Path.home()),
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=20,
                check=False,
            )
            if identity_check.returncode != 0:
                raise ValueError(_ssh_access_error(identity_check.stderr, known_hosts_file))
            native_console_mode = _native_console_mode(
                access,
                bool(getattr(ns, "native_consoles", False)),
            )
            console_ports: list[int] = []
            if native_console_mode == "eve-ng-qemu":
                console_ports = _discover_eve_qemu_console_ports(
                    ssh_base,
                    ssh_target,
                    known_hosts_file,
                )
                if console_ports:
                    _require_local_ports_available(console_ports)

            requested_port = int(getattr(ns, "local_port", 0) or 0) or int(access.get("local_port") or 0)
            port = _available_local_port(requested_port)
            if requested_port:
                _require_local_ports_available([port])
            url = f"http://127.0.0.1:{port}{path}"
            automation_session: dict[str, Any] | None = None
            socks_port = 0
            gateway = {
                "host": host,
                "user": ssh_user,
                "port": 22,
                "identity_file": str(ssh_key),
                "known_hosts_file": str(known_hosts_file),
                "host_key_alias": "",
                "ssh_command": ssh_base,
            }
            if automation:
                socks_port, automation_session = _prepare_automation_access(
                    ns=ns,
                    payload=payload,
                    paths=paths,
                    automation=automation,
                    gateway=gateway,
                    ssh_base=ssh_base,
                    ssh_target=ssh_target,
                    reserved_ports=[port, *console_ports],
                )
            argv = [*ssh_base, "-N", "-o", "ExitOnForwardFailure=yes"]
            argv.extend(["-L", f"127.0.0.1:{port}:127.0.0.1:{remote_port}"])
            if automation:
                argv.extend(["-D", f"127.0.0.1:{socks_port}"])
            for console_port in console_ports:
                argv.extend(["-L", f"127.0.0.1:{console_port}:127.0.0.1:{console_port}"])
            argv.append(ssh_target)

            if access_type == "ssh-tcp-forward":
                print("opening private TCP access")
                print(f"local endpoint: 127.0.0.1:{port}")
            else:
                print("opening private lab access")
                print(f"local URL: {url}")
            _print_guest_network_guidance(access)
            if automation and automation_session:
                _print_automation_access(
                    automation,
                    automation_session,
                    route_requested=bool(getattr(ns, "route_lab", False)),
                )
            if native_console_mode:
                _print_native_console_client_guidance(native_console_mode)
                print(
                    _native_console_status(
                        console_ports,
                        mode=native_console_mode,
                    )
                )
            proc = subprocess.Popen(argv, cwd=str(Path.home()))
            time.sleep(2)
            if proc.poll() is not None:
                _close_access_session(
                    paths,
                    session_record,
                    "interrupted",
                    reason=f"access tunnel exited during startup with rc={proc.returncode}",
                )
                return OPERATOR_ERROR
            if native_console_mode == "gns3-api":
                _wait_for_local_port(port, proc)
            if automation:
                _wait_for_local_port(socks_port, proc)
            automation_refresh = None
            if automation and automation_session:
                automation_refresh = _automation_refresher(
                    ns=ns,
                    payload=payload,
                    paths=paths,
                    automation=automation,
                    gateway=gateway,
                    ssh_base=ssh_base,
                    ssh_target=ssh_target,
                    socks_port=socks_port,
                    session=automation_session,
                )
            native_console_refresh = None
            if native_console_mode == "eve-ng-qemu":
                native_console_refresh, native_console_stop = _native_console_refresher(
                    ssh_base=ssh_base,
                    ssh_target=ssh_target,
                    known_hosts_file=known_hosts_file,
                    forwarded_ports=console_ports,
                )
            elif native_console_mode == "gns3-api":
                password_env = str(access["native_console_password_env"])
                native_console_refresh, native_console_stop = _gns3_console_refresher(
                    ssh_base=ssh_base,
                    ssh_target=ssh_target,
                    local_api_port=port,
                    username=str(access["native_console_username"]),
                    password=_runtime_access_secret(
                        paths,
                        str(getattr(ns, "env", "") or "default"),
                        password_env,
                    ),
                )
                native_console_refresh()
            maintenance = _combine_maintenance(
                automation_refresh,
                native_console_refresh,
            )
            route_proc: subprocess.Popen | None = None
            route_plan: dict[str, Any] | None = None
            if automation and bool(getattr(ns, "route_lab", False)):
                try:
                    print("preparing private lab route", flush=True)
                    route_proc, route_plan = _start_lab_route(
                        automation,
                        gateway,
                        scope=f"{paths.root}:{payload['blueprint_ref']}",
                    )
                    _print_lab_route_ready(automation)
                except BaseException:
                    if native_console_stop is not None:
                        native_console_stop()
                    _stop_process(proc)
                    raise
            if access_type != "ssh-tcp-forward" and not bool(getattr(ns, "no_browser", False)):
                open_operator_url(url)
            print("press Ctrl-C to close access")
            try:
                rc = _wait_for_managed_access(
                    proc,
                    route_proc,
                    maintenance=maintenance,
                    paths=paths,
                    session_record=session_record,
                )
                _stop_lab_route(route_proc, route_plan)
                if native_console_stop is not None:
                    native_console_stop()
                _stop_process(proc)
                if rc is None:
                    print("access closed")
                    return _expire_access_session(
                        ns,
                        payload,
                        paths,
                        session_record,
                    )
                _close_access_session(
                    paths,
                    session_record,
                    "completed",
                    reason=f"access process exited with rc={rc}",
                )
                return rc
            except KeyboardInterrupt:
                _stop_lab_route(route_proc, route_plan)
                if native_console_stop is not None:
                    native_console_stop()
                _stop_process(proc)
                print("access closed")
                _close_access_session(
                    paths,
                    session_record,
                    "cancelled",
                    reason="access closed by operator",
                )
                return _offer_access_close_destroy(ns, payload, state)

        vm_id = str(vm.get("vm_id") or "").strip()
        match = re.fullmatch(r"projects/([^/]+)/zones/([^/]+)/instances/([^/]+)", vm_id)
        if not match:
            raise ValueError("GCP VM state does not contain a usable instance id")
        project, zone, instance = match.groups()
        cost_estimate = _gcp_cost_estimate_with_progress(
            project_id=project,
            zone=zone,
            state=state,
            paths=paths,
        )
        port = _available_local_port(int(getattr(ns, "local_port", 0) or 0))
        if int(getattr(ns, "local_port", 0) or 0):
            _require_local_ports_available([port])
        url = f"http://127.0.0.1:{port}{path}"
        gcloud = shutil.which("gcloud")
        if not gcloud:
            raise ValueError("gcloud is required; run: hyops setup gcp")
        iap_proc: subprocess.Popen | None = None
        native_console_mode = _native_console_mode(
            access,
            bool(getattr(ns, "native_consoles", False)),
        )
        console_ports: list[int] = []
        if str(access.get("type") or "") == "gcp-iap-ssh-forward":
            ssh_user = str(access.get("ssh_user") or "").strip()
            ssh_key = str(Path(str(access.get("ssh_key_file") or "")).expanduser().resolve())
            if not Path(ssh_key).exists():
                raise ValueError(f"declared SSH key does not exist: {ssh_key}")
            ssh = shutil.which("ssh")
            if not ssh:
                raise ValueError("ssh is required; run: hyops setup base")
            iap_port = _available_local_port(0)
            while iap_port == port:
                iap_port = _available_local_port(0)
            print("preparing private GCP IAP access", flush=True)
            iap_argv = [
                gcloud,
                "compute",
                "start-iap-tunnel",
                instance,
                "22",
                "--project",
                project,
                "--zone",
                zone,
                f"--local-host-port=127.0.0.1:{iap_port}",
                "--verbosity=error",
            ]
            iap_proc = subprocess.Popen(iap_argv, cwd=str(Path.home()))
            _wait_for_local_port(iap_port, iap_proc)
            known_hosts_file = _access_known_hosts_file(paths, state_ref, state)
            ssh_base = [
                ssh,
                "-o",
                "BatchMode=yes",
                "-o",
                "IdentitiesOnly=yes",
                *_ssh_access_trust_options(
                    known_hosts_file,
                    host_key_alias=f"hyops-{known_hosts_file.stem}",
                ),
                "-i",
                ssh_key,
                "-p",
                str(iap_port),
            ]
            ssh_target = f"{ssh_user}@127.0.0.1"
            if native_console_mode == "eve-ng-qemu":
                console_ports = _discover_eve_qemu_console_ports(
                    ssh_base,
                    ssh_target,
                    known_hosts_file,
                )
                if console_ports:
                    _require_local_ports_available(console_ports)
            automation_session: dict[str, Any] | None = None
            socks_port = 0
            host_key_alias = f"hyops-{known_hosts_file.stem}"
            gateway = {
                "host": "127.0.0.1",
                "user": ssh_user,
                "port": iap_port,
                "identity_file": ssh_key,
                "known_hosts_file": str(known_hosts_file),
                "host_key_alias": host_key_alias,
                "ssh_command": ssh_base,
            }
            if automation:
                socks_port, automation_session = _prepare_automation_access(
                    ns=ns,
                    payload=payload,
                    paths=paths,
                    automation=automation,
                    gateway=gateway,
                    ssh_base=ssh_base,
                    ssh_target=ssh_target,
                    reserved_ports=[port, iap_port, *console_ports],
                )
            argv = [*ssh_base, "-N", "-o", "ExitOnForwardFailure=yes"]
            argv.extend(["-L", f"127.0.0.1:{port}:127.0.0.1:{remote_port}"])
            if automation:
                argv.extend(["-D", f"127.0.0.1:{socks_port}"])
            for console_port in console_ports:
                argv.extend(["-L", f"127.0.0.1:{console_port}:127.0.0.1:{console_port}"])
            argv.append(ssh_target)
        else:
            if automation:
                raise ValueError("device automation access requires an SSH-forward access path")
            if bool(getattr(ns, "native_consoles", False)):
                raise ValueError("native consoles require an SSH-forward access declaration")
            argv = [
                gcloud,
                "compute",
                "start-iap-tunnel",
                instance,
                str(remote_port),
                "--project",
                project,
                "--zone",
                zone,
                f"--local-host-port=127.0.0.1:{port}",
            ]
        open_browser = bool(access.get("open_browser", True))
        print("opening private GCP IAP access")
        if open_browser:
            print(f"local URL: {url}")
        else:
            print(f"local endpoint: 127.0.0.1:{port}")
        _print_guest_network_guidance(access)
        if automation and automation_session:
            _print_automation_access(
                automation,
                automation_session,
                route_requested=bool(getattr(ns, "route_lab", False)),
            )
        validated, enabled, _detail = diagnose_project_billing(project)
        print(
            f"billing: {'enabled' if enabled else 'disabled'}" if validated else "billing: unable to verify"
        )
        _print_cost_estimate(cost_estimate, state=state)
        if bool(getattr(ns, "native_consoles", False)):
            _print_native_console_client_guidance(native_console_mode)
            print(
                _native_console_status(
                    console_ports,
                    mode=native_console_mode,
                )
            )
        access_started_at = time.monotonic()
        proc = subprocess.Popen(argv, cwd=str(Path.home()))
        time.sleep(2)
        if proc.poll() is not None:
            _stop_process(iap_proc)
            _close_access_session(
                paths,
                session_record,
                "interrupted",
                reason=f"access tunnel exited during startup with rc={proc.returncode}",
            )
            return OPERATOR_ERROR
        if native_console_mode == "gns3-api":
            _wait_for_local_port(port, proc)
        if automation:
            _wait_for_local_port(socks_port, proc)
        automation_refresh = None
        if automation and automation_session:
            automation_refresh = _automation_refresher(
                ns=ns,
                payload=payload,
                paths=paths,
                automation=automation,
                gateway=gateway,
                ssh_base=ssh_base,
                ssh_target=ssh_target,
                socks_port=socks_port,
                session=automation_session,
            )
        native_console_refresh = None
        if native_console_mode == "eve-ng-qemu":
            native_console_refresh, native_console_stop = _native_console_refresher(
                ssh_base=ssh_base,
                ssh_target=ssh_target,
                known_hosts_file=known_hosts_file,
                forwarded_ports=console_ports,
            )
        elif native_console_mode == "gns3-api":
            password_env = str(access["native_console_password_env"])
            native_console_refresh, native_console_stop = _gns3_console_refresher(
                ssh_base=ssh_base,
                ssh_target=ssh_target,
                local_api_port=port,
                username=str(access["native_console_username"]),
                password=_runtime_access_secret(
                    paths,
                    str(getattr(ns, "env", "") or "default"),
                    password_env,
                ),
            )
            native_console_refresh()
        maintenance = _combine_maintenance(
            automation_refresh,
            native_console_refresh,
        )
        route_proc: subprocess.Popen | None = None
        route_plan: dict[str, Any] | None = None
        if automation and bool(getattr(ns, "route_lab", False)):
            try:
                print("preparing private lab route", flush=True)
                route_proc, route_plan = _start_lab_route(
                    automation,
                    gateway,
                    scope=f"{paths.root}:{payload['blueprint_ref']}",
                )
                _print_lab_route_ready(automation)
            except BaseException:
                if native_console_stop is not None:
                    native_console_stop()
                _stop_process(proc)
                _stop_process(iap_proc)
                raise
        if open_browser and not bool(getattr(ns, "no_browser", False)):
            open_operator_url(url)
        print("press Ctrl-C to close access")
        try:
            rc = _wait_for_managed_access(
                proc,
                route_proc,
                maintenance=maintenance,
                paths=paths,
                session_record=session_record,
            )
            _stop_lab_route(route_proc, route_plan)
            if native_console_stop is not None:
                native_console_stop()
            _stop_process(proc)
            _stop_process(iap_proc)
            if rc is None:
                print("access closed")
                return _expire_access_session(
                    ns,
                    payload,
                    paths,
                    session_record,
                    cost_estimate=cost_estimate,
                )
            _close_access_session(
                paths,
                session_record,
                "completed",
                reason=f"access process exited with rc={rc}",
            )
            return rc
        except KeyboardInterrupt:
            _stop_lab_route(route_proc, route_plan)
            if native_console_stop is not None:
                native_console_stop()
            _stop_process(proc)
            _stop_process(iap_proc)
            print("access closed")
            _close_access_session(
                paths,
                session_record,
                "cancelled",
                reason="access closed by operator",
            )
            return _offer_access_close_destroy(
                ns,
                payload,
                state,
                project_id=project,
                cost_estimate=cost_estimate,
                access_started_at=access_started_at,
            )
    except KeyboardInterrupt:
        if native_console_stop is not None:
            native_console_stop()
        if "route_proc" in locals():
            _stop_lab_route(route_proc, route_plan)
        if "proc" in locals():
            _stop_process(proc)
        if "iap_proc" in locals():
            _stop_process(iap_proc)
        if paths is not None:
            _close_access_session(
                paths,
                session_record,
                "cancelled",
                reason="access interrupted by operator",
            )
        raise
    except Exception as exc:
        if native_console_stop is not None:
            native_console_stop()
        if "route_proc" in locals():
            _stop_lab_route(route_proc, route_plan)
        if "proc" in locals():
            _stop_process(proc)
        if "iap_proc" in locals():
            _stop_process(iap_proc)
        if paths is not None:
            _close_access_session(
                paths,
                session_record,
                "interrupted",
                reason=str(exc),
            )
        print(f"ERR: blueprint access failed: {exc}")
        return OPERATOR_ERROR


def _lab_archive_contract(lifecycle: dict[str, Any]) -> dict[str, Any]:
    prefix = str(lifecycle.get("contract_prefix") or "eveng_lab_archive").strip()
    return {
        "prefix": prefix,
        "contents_label": str(lifecycle.get("contents_label") or "lab definitions").strip(),
        "node_state": bool(lifecycle.get("node_state", True)),
        "restore_overwrite_default": bool(lifecycle.get("restore_overwrite_default", False)),
        "path_output": f"{prefix}_path",
        "previous_path_output": f"{prefix}_previous_path",
        "sha256_output": f"{prefix}_sha256",
        "node_included_output": f"{prefix}_node_state_included",
        "node_path_output": f"{prefix}_node_state_archive_path",
        "node_sha256_output": f"{prefix}_node_state_sha256",
        "images_included_output": f"{prefix}_images_included",
        "images_path_output": f"{prefix}_images_archive_path",
        "images_sha256_output": f"{prefix}_images_sha256",
        "device_configs_captured_output": f"{prefix}_device_configs_captured",
    }


def _verified_lab_archive(
    payload: dict[str, Any],
    paths,
) -> tuple[Path, str, Path | None, str, Path | None, str] | None:
    lifecycle = payload.get("archive_before_destroy")
    if not isinstance(lifecycle, dict) or not lifecycle:
        return None

    try:
        state = read_module_state(
            paths.state_dir,
            lifecycle["module_ref"],
            state_instance=lifecycle["state_instance"],
        )
    except FileNotFoundError:
        state = {}
    outputs = state.get("outputs") if isinstance(state.get("outputs"), dict) else {}
    contract = _lab_archive_contract(lifecycle)
    archive_value = str(outputs.get(contract["path_output"]) or "").strip()
    expected = str(outputs.get(contract["sha256_output"]) or "").strip().lower()
    if not archive_value and not expected:
        from hyops.lab.migration import load_migration_archive

        return load_migration_archive(paths=paths, payload=payload)
    archive_path = Path(archive_value).expanduser()
    if not archive_path.is_file() or not re.fullmatch(r"[0-9a-f]{64}", expected):
        return None

    digest = hashlib.sha256()
    with archive_path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    if digest.hexdigest() != expected:
        raise ValueError(f"lab archive checksum verification failed: {archive_path}")

    node_archive: Path | None = None
    node_checksum = ""
    if contract["node_state"]:
        candidate_value = str(outputs.get(contract["node_path_output"]) or "").strip()
        candidate_checksum = str(outputs.get(contract["node_sha256_output"]) or "").strip().lower()
        node_state_declared = bool(outputs.get(contract["node_included_output"], False))
        node_state_metadata_present = bool(candidate_value or candidate_checksum)
        if node_state_declared or node_state_metadata_present:
            candidate = Path(candidate_value).expanduser()
            if not candidate.is_file() or not re.fullmatch(r"[0-9a-f]{64}", candidate_checksum):
                raise ValueError("node-state archive is missing or unverifiable")
            node_digest = hashlib.sha256()
            with candidate.open("rb") as handle:
                for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                    node_digest.update(chunk)
            if node_digest.hexdigest() != candidate_checksum:
                raise ValueError(f"node-state archive checksum verification failed: {candidate}")
            node_archive = candidate.resolve()
            node_checksum = candidate_checksum
    image_archive: Path | None = None
    image_checksum = ""
    candidate_value = str(outputs.get(contract["images_path_output"]) or "").strip()
    candidate_checksum = str(outputs.get(contract["images_sha256_output"]) or "").strip().lower()
    images_declared = bool(outputs.get(contract["images_included_output"], False))
    if images_declared or candidate_value or candidate_checksum:
        candidate = Path(candidate_value).expanduser()
        if not candidate.is_file() or not re.fullmatch(r"[0-9a-f]{64}", candidate_checksum):
            raise ValueError("image archive is missing or unverifiable")
        image_digest = hashlib.sha256()
        with candidate.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                image_digest.update(chunk)
        if image_digest.hexdigest() != candidate_checksum:
            raise ValueError(f"image archive checksum verification failed: {candidate}")
        image_archive = candidate.resolve()
        image_checksum = candidate_checksum
    else:
        from hyops.lab.migration import load_migration_images

        migrated_images = load_migration_images(paths=paths, payload=payload)
        if migrated_images is not None:
            image_archive, image_checksum = migrated_images
    return (
        archive_path.resolve(),
        expected,
        node_archive,
        node_checksum,
        image_archive,
        image_checksum,
    )


def _automatic_lab_restore_eligible(payload: dict[str, Any], paths) -> bool:
    lifecycle = payload.get("archive_before_destroy")
    if not isinstance(lifecycle, dict) or not lifecycle:
        return False
    inputs = lifecycle.get("inputs")
    if not isinstance(inputs, dict):
        return True
    target_state_ref = str(inputs.get("inventory_state_ref") or "").strip()
    if not target_state_ref:
        return True
    target_status = module_state_status(paths.state_dir, target_state_ref)
    return not target_status or target_status in {"absent", "destroyed", "missing"}


def _select_lab_restore_mode(
    ns,
    payload: dict[str, Any],
    paths,
    *,
    automatic_restore_eligible: bool = True,
) -> tuple[
    str,
    tuple[Path, str, Path | None, str, Path | None, str] | None,
]:
    lifecycle = payload.get("archive_before_destroy")
    requested = bool(getattr(ns, "restore_labs", False))
    skipped = bool(getattr(ns, "skip_lab_restore", False))
    overwrite = bool(getattr(ns, "overwrite_labs", False))
    overwrite_images = bool(getattr(ns, "overwrite_images", False))

    if overwrite and not requested:
        raise ValueError("--overwrite-labs requires --restore-labs")
    if overwrite_images and not requested:
        raise ValueError("--overwrite-images requires --restore-labs")
    if (requested or skipped) and not isinstance(lifecycle, dict):
        raise ValueError("this blueprint does not declare a lab archive lifecycle")

    archive = _verified_lab_archive(payload, paths)
    if archive is None:
        if requested:
            raise ValueError("no verified lab archive is available for this environment")
        return "none", None
    if overwrite_images and archive[4] is None:
        raise ValueError("--overwrite-images requires a verified image archive")
    if requested:
        return "restore", archive
    if skipped:
        return "skip", archive
    if not automatic_restore_eligible:
        return "none", archive
    if bool(getattr(ns, "yes", False)) or bool(getattr(ns, "json", False)):
        return "skip", archive
    if not (sys.stdin.isatty() and sys.stdout.isatty()):
        return "skip", archive

    print(f"lab archive available: {archive[0]}")
    if archive[2] is not None:
        print(f"stopped node state available: {archive[2]}")
    if archive[4] is not None:
        print(f"referenced base images available: {archive[4]}")
    confirmed = _prompt_yes_no("Restore archived labs? [y/N]: ")
    if confirmed is None:
        return "skip", archive
    return ("restore" if confirmed else "skip"), archive


def _run_lab_restore(
    ns,
    payload: dict[str, Any],
    paths,
    archive: tuple[Path, str, Path | None, str, Path | None, str],
) -> int:
    lifecycle = payload["archive_before_destroy"]
    contract = _lab_archive_contract(lifecycle)
    prefix = contract["prefix"]
    (
        archive_path,
        checksum,
        node_archive_path,
        node_checksum,
        image_archive_path,
        image_checksum,
    ) = archive
    restore_inputs = dict(lifecycle.get("inputs") or {})
    restore_inputs.update(
        {
            f"{prefix}_action": "restore",
            f"{prefix}_path": str(archive_path),
            f"{prefix}_expected_sha256": checksum,
            f"{prefix}_overwrite": bool(getattr(ns, "overwrite_labs", False))
            or contract["restore_overwrite_default"],
        }
    )
    capture_key = f"{prefix}_capture_device_configs"
    if capture_key in restore_inputs:
        restore_inputs[capture_key] = False
    if contract["node_state"]:
        restore_inputs.update(
            {
                f"{prefix}_include_node_state": False,
                f"{prefix}_stop_running_nodes": False,
            }
        )
    if contract["node_state"] and node_archive_path is not None:
        restore_inputs.update(
            {
                f"{prefix}_restore_node_state": True,
                f"{prefix}_node_state_path": str(node_archive_path),
                f"{prefix}_node_state_expected_sha256": node_checksum,
            }
        )
    if image_archive_path is not None:
        restore_inputs.update(
            {
                f"{prefix}_restore_images": True,
                f"{prefix}_overwrite_images": bool(getattr(ns, "overwrite_images", False)),
                f"{prefix}_images_path": str(image_archive_path),
                f"{prefix}_images_expected_sha256": image_checksum,
            }
        )
    restore_step = {
        "id": "restore_archived_labs",
        "module_ref": lifecycle["module_ref"],
        "state_instance": lifecycle["state_instance"],
        "action": "deploy",
        "phase": "operations",
        "with_deps": False,
        "inputs": restore_inputs,
    }
    print(f"restoring lab archive: {archive_path}")
    progress = ProgressDisplay(
        enabled=bool(
            sys.stdout
            and sys.stdout.isatty()
            and not bool(getattr(ns, "json", False))
            and not os.getenv("HYOPS_VERBOSE")
        ),
        show_elapsed=False,
    )
    progress.start(
        restore_step["id"],
        "Lab restore",
        plain="lab_restore status=running",
    )
    previous_child = os.environ.get("HYOPS_PROGRESS_CHILD")
    if not os.getenv("HYOPS_VERBOSE"):
        os.environ["HYOPS_PROGRESS_CHILD"] = "1"
    try:
        rc = int(run_step_module_command(restore_step, payload, ns, paths))
    except KeyboardInterrupt:
        rc = CANCELLED
    finally:
        if previous_child is None:
            os.environ.pop("HYOPS_PROGRESS_CHILD", None)
        else:
            os.environ["HYOPS_PROGRESS_CHILD"] = previous_child
    restore_status = "cancelled" if rc == CANCELLED else ("ok" if rc == 0 else "failed")
    progress.finish(
        restore_step["id"],
        "Lab restore",
        restore_status,
        plain=f"lab_restore status={restore_status}",
    )
    if rc == CANCELLED:
        print("Lab restore interrupted. Deployed resources were retained.")
        return rc
    if rc != 0:
        print("ERR: lab restore failed; deployed resources were retained")
        return rc
    print("lab restore: ok")
    return 0


def run_deploy(ns) -> int:
    try:
        payload = _resolve_and_validate(ns)
    except Exception as exc:
        print(f"ERR: blueprint deploy failed: {format_runtime_storage_error(exc)}")
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
        require_runtime_writable(paths.root)
        _enforce_runtime_blueprint_file_scope(
            ns,
            paths,
            command_label="hyops blueprint deploy",
        )
    except Exception as exc:
        print(f"ERR: blueprint deploy failed: {format_runtime_storage_error(exc)}")
        return OPERATOR_ERROR

    skip_preflight = bool(getattr(ns, "skip_preflight", False))
    try:
        preflight_bypass_reason = validate_preflight_bypass(
            command="deploy",
            skip_preflight=skip_preflight,
            reason=getattr(ns, "preflight_bypass_reason", None),
        )
    except ValueError as exc:
        print(f"ERR: blueprint deploy failed: {exc}")
        return OPERATOR_ERROR

    preflight_decision = new_preflight_decision(
        command="deploy",
        skip_preflight=skip_preflight,
        reason=preflight_bypass_reason,
        scope="blueprint",
    )
    preflight_summary: dict[str, Any] | None = None
    if not skip_preflight:
        preflight_steps, preflight_required, preflight_optional = compute_preflight(payload, ns, paths)
        preflight_status = "ok" if not preflight_required else "failed"
        preflight_decision = complete_preflight_decision(
            preflight_decision,
            passed=not preflight_required,
            detail=("" if not preflight_required else f"required_failures={','.join(preflight_required)}"),
        )
        preflight_summary = {
            "status": preflight_status,
            "required_failures": list(preflight_required),
            "optional_failures": list(preflight_optional),
            "steps": preflight_steps,
        }
        ns.preflight_context = preflight_decision
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
    elif not json_mode:
        print("WARN: blueprint preflight bypassed; decision will be recorded with executed steps")

    ns.preflight_context = preflight_decision

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

    automatic_lab_restore_eligible = _automatic_lab_restore_eligible(payload, paths)
    by_id = {step["id"]: step for step in payload["steps"]}
    fail_fast = bool(payload["policy"].get("fail_fast", True))
    step_results: list[dict[str, Any]] = []
    required_failures: list[str] = []
    optional_failures: list[str] = []
    cancelled = False
    iol_repair_used = False
    repair_results: list[dict[str, Any]] = []
    progress = ProgressDisplay(
        enabled=bool(sys.stdout and sys.stdout.isatty() and not json_mode and not os.getenv("HYOPS_VERBOSE")),
        show_elapsed=False,
    )

    total_steps = len(payload["order"])
    for step_position, step_id in enumerate(payload["order"], start=1):
        step = by_id[step_id]
        progress_before = int(((step_position - 1) * 100) / total_steps) if total_steps else 0
        progress_after = int((step_position * 100) / total_steps) if total_steps else 100
        display_label = _step_display_label(step)
        running_label = f"{display_label}  stage {step_position}/{total_steps}"
        completed_label = display_label
        completed_detail = f"overall {progress_after}%"
        item_line = ""
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
                    skip_label, skip_detail, skip_item_line = _step_presentation(
                        step,
                        state_dir=paths.state_dir,
                        progress_after=progress_after,
                    )
                    result = dict(base)
                    result.update({"status": "skipped", "reason": "state-ok", "rc": 0})
                    step_results.append(result)
                    progress.finish(
                        step_id,
                        skip_label,
                        "skipped",
                        plain=f"step={step_id} status=skipped reason=state-ok",
                        detail=f"existing, {skip_detail}",
                    )
                    if skip_item_line and progress.enabled:
                        print(skip_item_line)
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
                    presentation_label, presentation_detail, skip_item_line = _step_presentation(
                        step,
                        state_dir=paths.state_dir,
                        progress_after=progress_after,
                    )
                    result = dict(base)
                    result.update({"status": "skipped", "reason": detail, "rc": 0})
                    step_results.append(result)
                    progress.finish(
                        step_id,
                        presentation_label,
                        "skipped",
                        plain=f"step={step_id} status=skipped reason={detail}",
                        detail=f"existing, {presentation_detail}",
                    )
                    if skip_item_line and progress.enabled:
                        print(skip_item_line)
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

        progress.start(
            step_id,
            running_label,
            plain=(f"step={step_id} status=running action={step['action']} module={step['module_ref']}"),
        )
        previous_child = os.environ.get("HYOPS_PROGRESS_CHILD")
        failure_state_before = _step_failure_state(step, paths)
        if not os.getenv("HYOPS_VERBOSE"):
            os.environ["HYOPS_PROGRESS_CHILD"] = "1"
        try:
            rc = run_step_module_command(step, payload, ns, paths)
        except KeyboardInterrupt:
            rc = CANCELLED
            err = "cancelled by user"
        except Exception as exc:
            rc = OPERATOR_ERROR
            err = format_runtime_storage_error(exc)
        else:
            err = ""
        finally:
            if previous_child is None:
                os.environ.pop("HYOPS_PROGRESS_CHILD", None)
            else:
                os.environ["HYOPS_PROGRESS_CHILD"] = previous_child

        if rc != 0 and not err:
            err = _new_step_failure_detail(step, paths, failure_state_before)

        mismatch = parse_iol_mismatch(err) if rc != 0 else None
        if (
            rc != 0
            and mismatch is not None
            and bool(getattr(ns, "repair_iol_license", False))
            and not iol_repair_used
            and str(step.get("module_ref") or "").strip().lower() == IOL_IMAGES_MODULE_REF
            and str(step.get("action") or "").strip().lower() in {"apply", "deploy"}
        ):
            iol_repair_used = True
            try:
                repair = repair_iol_license(
                    ns,
                    paths,
                    state_ref=step_state_ref(step),
                    mismatch=mismatch,
                )
            except IolRepairError as exc:
                err = f"{err} IOL licence repair failed: {exc}".strip()
                repair_results.append(
                    {
                        "step_id": step_id,
                        "status": "failed",
                        "hostname": mismatch.hostname,
                        "host_id": mismatch.host_id,
                        "reason": str(exc),
                    }
                )
            else:
                repair_results.append(
                    {
                        "step_id": step_id,
                        "status": "stored",
                        "hostname": repair.hostname,
                        "host_id": repair.host_id,
                        "request_id": repair.request_id,
                        "persisted_to": repair.persisted_to,
                    }
                )
                if not json_mode:
                    print(
                        f"step={step_id} repair=stored host={repair.hostname} "
                        f"authority={repair.persisted_to}; retrying once"
                    )
                retry_failure_before = _step_failure_state(step, paths)
                previous_child = os.environ.get("HYOPS_PROGRESS_CHILD")
                if not os.getenv("HYOPS_VERBOSE"):
                    os.environ["HYOPS_PROGRESS_CHILD"] = "1"
                try:
                    rc = run_step_module_command(step, payload, ns, paths)
                except KeyboardInterrupt:
                    rc = CANCELLED
                    err = "cancelled by user"
                except Exception as exc:
                    rc = OPERATOR_ERROR
                    err = format_runtime_storage_error(exc)
                else:
                    err = ""
                finally:
                    if previous_child is None:
                        os.environ.pop("HYOPS_PROGRESS_CHILD", None)
                    else:
                        os.environ["HYOPS_PROGRESS_CHILD"] = previous_child
                if rc != 0 and not err:
                    err = _new_step_failure_detail(step, paths, retry_failure_before)
                repair_results[-1]["status"] = "ok" if rc == 0 else "retry-failed"

        if rc == 0:
            completed_label, completed_detail, item_line = _step_presentation(
                step,
                state_dir=paths.state_dir,
                progress_after=progress_after,
            )
            result = dict(base)
            result.update({"status": "ok", "rc": 0})
            step_results.append(result)
            progress.finish(
                step_id,
                completed_label,
                "ok",
                plain=f"step={step_id} status=ok progress={progress_after}%",
                detail=completed_detail,
            )
            if item_line and progress.enabled:
                print(item_line)
            continue

        result = dict(base)
        result.update({"status": "failed", "rc": int(rc), "reason": err or "step command failed"})
        if int(rc) == CANCELLED:
            result["status"] = "cancelled"
            step_results.append(result)
            cancelled = True
            progress.finish(
                step_id,
                step_id,
                "cancelled",
                plain=f"step={step_id} status=cancelled rc={rc}",
                detail=f"overall {progress_before}%",
            )
            break
        if step["optional"]:
            result["status"] = "failed-optional"
            optional_failures.append(step_id)
            step_results.append(result)
            progress.finish(
                step_id,
                step_id,
                "failed-optional",
                plain=f"step={step_id} status=failed-optional rc={rc}",
                detail=completed_detail,
            )
            continue

        required_failures.append(step_id)
        step_results.append(result)
        failure_detail = err or "see module run record"
        progress.finish(
            step_id,
            display_label,
            "failed",
            plain=f"step={step_id} status=failed rc={rc} reason={failure_detail}",
            detail=f"overall {progress_before}%",
        )
        if progress.enabled and err:
            print(f"error: {failure_detail}", file=sys.stderr)
        if fail_fast:
            break

    if not required_failures and not cancelled:
        try:
            restore_mode, lab_archive = _select_lab_restore_mode(
                ns,
                payload,
                paths,
                automatic_restore_eligible=automatic_lab_restore_eligible,
            )
        except (OSError, ValueError) as exc:
            required_failures.append("restore_archived_labs")
            step_results.append(
                {
                    "id": "restore_archived_labs",
                    "module_ref": str((payload.get("archive_before_destroy") or {}).get("module_ref", "")),
                    "action": "deploy",
                    "phase": "operations",
                    "optional": False,
                    "status": "failed",
                    "rc": OPERATOR_ERROR,
                    "reason": str(exc),
                }
            )
            print(f"ERR: lab restore preparation failed: {exc}")
        else:
            if restore_mode == "restore" and lab_archive is not None:
                restore_rc = _run_lab_restore(ns, payload, paths, lab_archive)
                restore_status = "ok" if restore_rc == 0 else "failed"
                step_results.append(
                    {
                        "id": "restore_archived_labs",
                        "module_ref": payload["archive_before_destroy"]["module_ref"],
                        "action": "deploy",
                        "phase": "operations",
                        "optional": False,
                        "status": restore_status,
                        "rc": restore_rc,
                    }
                )
                if restore_rc != 0:
                    required_failures.append("restore_archived_labs")
            elif restore_mode == "skip" and lab_archive is not None:
                print("lab archive retained; deploy again with --restore-labs to restore it")

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
        "preflight_decision": preflight_decision,
    }
    if preflight_summary is not None:
        output["preflight"] = preflight_summary
    if repair_results:
        output["iol_license_repairs"] = repair_results
    if cancelled:
        output["next_actions"] = _cancelled_deploy_actions(ns, payload)
    elif required_failures and _failed_deploy_has_resources(payload, paths):
        output["next_actions"] = {"destroy": _cancelled_deploy_actions(ns, payload)["destroy"]}

    if json_mode:
        print(json.dumps(output, indent=2, sort_keys=True))
    else:
        ready_message = str((payload.get("metadata") or {}).get("ready_message") or "").strip()
        if final_status == "ok" and ready_message and progress.enabled:
            print()
            progress.finish(
                "blueprint-ready",
                ready_message,
                "ok",
                plain=f"blueprint={payload['blueprint_ref']} status=ready",
            )
        print(
            f"blueprint={payload['blueprint_ref']} mode={payload['mode']} "
            f"status={final_status} steps={len(step_results)}"
        )
        if required_failures:
            print(f"required_failures: {', '.join(required_failures)}")
        if optional_failures:
            print(f"optional_failures: {', '.join(optional_failures)}")
        if cancelled:
            print("deployment cancelled; completed resources were retained.")
            print("resume:")
            print(f"  {output['next_actions']['resume']}")
            print("remove:")
            print(f"  {output['next_actions']['destroy']}")
        elif required_failures:
            _offer_failed_deploy_destroy(ns, payload, paths)

    if cancelled:
        return CANCELLED
    return 0 if not required_failures else OPERATOR_ERROR


def _select_archive_destroy_mode(ns, payload: dict[str, Any], env_name: str) -> str:
    archive = payload.get("archive_before_destroy")
    if not isinstance(archive, dict) or not archive:
        if (
            bool(getattr(ns, "archive_before_destroy", False))
            or bool(getattr(ns, "skip_archive", False))
            or bool(getattr(ns, "guest_quiesced", False))
        ):
            raise ValueError("this blueprint does not declare a lab archive lifecycle")
        return "none"

    if bool(getattr(ns, "archive_before_destroy", False)):
        return "archive"
    if bool(getattr(ns, "skip_archive", False)):
        if bool(getattr(ns, "guest_quiesced", False)):
            raise ValueError("--guest-quiesced requires --archive-before-destroy")
        return "skip"

    if bool(getattr(ns, "yes", False)) or not (sys.stdin.isatty() and sys.stdout.isatty()):
        raise ValueError(
            "this blueprint protects lab data; select --archive-before-destroy or --skip-archive"
        )

    print("lab data:")
    print("  1. Keep the environment running")
    print("  2. Preserve saved lab state, then destroy")
    print("  3. Destroy without preserving lab state")
    choices = {"1": "keep", "2": "archive", "3": "skip"}
    while True:
        try:
            answer = input("Choose [1-3]: ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return "cancel"
        selected = choices.get(answer)
        if selected is not None:
            return selected
        print("invalid choice; enter exactly 1, 2, or 3")


def _archive_requires_guest_quiescence(payload: dict[str, Any]) -> bool:
    archive = payload.get("archive_before_destroy")
    if not isinstance(archive, dict):
        return False
    inputs = archive.get("inputs")
    if not isinstance(inputs, dict):
        return False
    return bool(inputs.get("eveng_lab_archive_include_node_state", False))


def _confirm_guest_quiescence(ns, payload: dict[str, Any]) -> bool | None:
    if not _archive_requires_guest_quiescence(payload):
        if bool(getattr(ns, "guest_quiesced", False)):
            raise ValueError(
                "--guest-quiesced is valid only for EVE-NG node-state archives"
            )
        return True
    if bool(getattr(ns, "guest_quiesced", False)):
        return True
    if bool(getattr(ns, "yes", False)) or not (
        sys.stdin.isatty() and sys.stdout.isatty()
    ):
        raise ValueError(
            "EVE-NG node-state archive requires --guest-quiesced after shutting "
            "down each stateful guest inside its operating system"
        )
    return _prompt_yes_no(
        "Confirm stateful guests were shut down inside their operating systems "
        "[y/N]: "
    )


def _confirm_archive_destroy(env_name: str) -> bool | None:
    confirmation = f"destroy {env_name}"
    while True:
        try:
            typed = input(f'Type "{confirmation}" to confirm: ').strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return None
        if typed == confirmation:
            return True
        print(f'confirmation did not match; type exactly "{confirmation}"')


def _run_archive_before_destroy(ns, payload: dict[str, Any], paths) -> int:
    archive = payload["archive_before_destroy"]
    archive_step = {
        "id": "archive_before_destroy",
        "module_ref": archive["module_ref"],
        "state_instance": archive["state_instance"],
        "action": "deploy",
        "phase": "operations",
        "with_deps": False,
        "inputs": archive.get("inputs") or {},
    }
    print("preparing saved lab state; guests must already be shut down")
    print("this may take several minutes, depending on lab size")
    progress = ProgressDisplay(
        enabled=bool(
            sys.stdout
            and sys.stdout.isatty()
            and not bool(getattr(ns, "json", False))
            and not os.getenv("HYOPS_VERBOSE")
        ),
        show_elapsed=False,
    )
    progress.start(
        archive_step["id"],
        "Lab archive",
        plain="lab_archive status=running",
    )
    previous_child = os.environ.get("HYOPS_PROGRESS_CHILD")
    if not os.getenv("HYOPS_VERBOSE"):
        os.environ["HYOPS_PROGRESS_CHILD"] = "1"
    try:
        rc = run_step_module_command(archive_step, payload, ns, paths)
    except KeyboardInterrupt:
        rc = CANCELLED
    finally:
        if previous_child is None:
            os.environ.pop("HYOPS_PROGRESS_CHILD", None)
        else:
            os.environ["HYOPS_PROGRESS_CHILD"] = previous_child
    archive_status = "cancelled" if int(rc) == CANCELLED else ("ok" if rc == 0 else "failed")
    progress.finish(
        archive_step["id"],
        "Lab archive",
        archive_status,
        plain=f"lab_archive status={archive_status}",
    )
    if int(rc) == CANCELLED:
        print("Archive interrupted. Resources were retained.")
        print("Check lab state before continuing.")
        return CANCELLED
    if rc != 0:
        print("ERR: lab export failed; no resources were destroyed")
        return int(rc)

    try:
        state = read_module_state(
            paths.state_dir,
            archive["module_ref"],
            state_instance=archive["state_instance"],
        )
        outputs = state.get("outputs") if isinstance(state.get("outputs"), dict) else {}
        contract = _lab_archive_contract(archive)
        archive_path = Path(str(outputs.get(contract["path_output"]) or "")).expanduser()
        expected = str(outputs.get(contract["sha256_output"]) or "").strip().lower()
        if not archive_path.is_file() or not expected:
            raise ValueError("lab export did not publish a verifiable archive")
        digest = hashlib.sha256()
        with archive_path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
    except (OSError, ValueError) as exc:
        print(f"ERR: {exc}; no resources were destroyed")
        return OPERATOR_ERROR
    actual = digest.hexdigest()
    if actual != expected:
        print("ERR: lab archive checksum verification failed; no resources were destroyed")
        return OPERATOR_ERROR
    archive_contents = [contract["contents_label"]]
    if bool(outputs.get(contract["device_configs_captured_output"], False)):
        archive_contents.append("saved device configurations")
    previous_archive_path = Path(str(outputs.get(contract["previous_path_output"]) or "")).expanduser()
    if previous_archive_path.is_file():
        archive_contents.append("previous generation retained")
    verbose = bool(os.getenv("HYOPS_VERBOSE"))
    if verbose:
        print(f"lab archive: {archive_path}")
        print(f"sha256: {actual}")
    if contract["node_state"] and bool(outputs.get(contract["node_included_output"], False)):
        node_archive_path = Path(str(outputs.get(contract["node_path_output"]) or "")).expanduser()
        node_expected = str(outputs.get(contract["node_sha256_output"]) or "").strip().lower()
        if not node_archive_path.is_file() or not re.fullmatch(r"[0-9a-f]{64}", node_expected):
            print("ERR: node-state archive is missing; no resources were destroyed")
            return OPERATOR_ERROR
        node_digest = hashlib.sha256()
        with node_archive_path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                node_digest.update(chunk)
        node_actual = node_digest.hexdigest()
        if node_actual != node_expected:
            print("ERR: node-state archive checksum verification failed; no resources were destroyed")
            return OPERATOR_ERROR
        archive_contents.append("stopped node state")
        if verbose:
            print(f"stopped node state: {node_archive_path}")
            print(f"sha256: {node_actual}")
    elif contract["node_state"]:
        print("node state: no QEMU overlays found")
    print(f"archive saved: {', '.join(archive_contents)}")
    return 0


def run_destroy(ns) -> int:
    if not bool(getattr(ns, "execute", False)) or bool(getattr(ns, "_lifecycle_lock_held", False)):
        return _run_destroy_unlocked(ns)
    try:
        require_runtime_selection(
            getattr(ns, "root", None),
            getattr(ns, "env", None),
            command_label="hyops blueprint destroy",
        )
        paths = resolve_runtime_paths(
            getattr(ns, "root", None),
            getattr(ns, "env", None),
        )
        ensure_layout(paths)
        with LifecycleLock(paths, "blueprint destroy"):
            setattr(ns, "_lifecycle_lock_held", True)
            try:
                return _run_destroy_unlocked(ns)
            finally:
                setattr(ns, "_lifecycle_lock_held", False)
    except (LifecycleBusy, OSError, ValueError) as exc:
        print(f"ERR: blueprint destroy failed: {exc}")
        return OPERATOR_ERROR


def _run_destroy_unlocked(ns) -> int:
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
                action = "retain" if bool(step.get("retain_on_destroy", False)) else "destroy"
                print(f"  - {_step_display_label(step)}: {action}")
                if os.getenv("HYOPS_VERBOSE"):
                    print(f"    id={step_id} module={step['module_ref']} ref={step_state_ref(step)}")
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
        require_runtime_writable(paths.root)
        _enforce_runtime_blueprint_file_scope(
            ns,
            paths,
            command_label="hyops blueprint destroy",
        )
    except Exception as exc:
        print(f"ERR: blueprint destroy failed: {format_runtime_storage_error(exc)}")
        return OPERATOR_ERROR

    by_id = {step["id"]: step for step in payload["steps"]}
    env_name = str(getattr(ns, "env", None) or getattr(paths.root, "name", "") or "").strip() or "default"
    lifecycle_snapshot = _destroy_lifecycle_snapshot(
        payload,
        paths,
        estimate=getattr(ns, "_cost_estimate", None),
    )
    token = re.sub(r"[^A-Za-z0-9_.-]+", "_", payload["blueprint_ref"])
    run_id = new_run_id("destroy")
    logs_dir = getattr(paths, "logs_dir", None)
    record_dir = Path(logs_dir) / "blueprint" / token / run_id if logs_dir else None
    if record_dir is not None:
        record_dir.mkdir(parents=True, exist_ok=True)
    record_writer = EvidenceWriter(record_dir) if record_dir is not None else None

    def record_destroy_outcome(
        status: str,
        *,
        archive: str,
        resources: str,
        steps: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any] | None:
        lifecycle = _complete_destroy_lifecycle(
            lifecycle_snapshot,
            archive=archive,
            resources=resources,
        )
        if record_writer is not None:
            record_writer.write_json(
                "destroy.json",
                {
                    "blueprint_ref": payload["blueprint_ref"],
                    "env": env_name,
                    "run_id": run_id,
                    "status": status,
                    "guest_quiesced": bool(
                        getattr(ns, "guest_quiesced", False)
                    ),
                    "lifecycle": lifecycle,
                    "steps": steps or [],
                },
            )
        return lifecycle

    def print_destroy_record() -> None:
        if record_dir is not None:
            print(f"run record: {record_dir}")

    record_destroy_outcome(
        "running",
        archive="pending",
        resources="active",
    )

    if not bool(getattr(ns, "yes", False)) and not json_mode:
        print(f"WARN: destroy resources in env={env_name}.")
        print("resources:")
        for step_id in destroy_order:
            step = by_id[step_id]
            state_ref = step_state_ref(step)
            status = module_state_status(paths.state_dir, state_ref) or "missing"
            preview_status = "pending" if _destroy_gate_required(step, by_id, paths) else status
            print(f"  - {_destroy_preview_label(step, preview_status)}")
            if os.getenv("HYOPS_VERBOSE"):
                print(f"    id={step_id} module={step['module_ref']} state={status} ref={state_ref}")
        cost_estimate = getattr(ns, "_cost_estimate", None)
        if cost_estimate is None and lifecycle_snapshot is not None:
            estimate_payload = lifecycle_snapshot["estimate"]
            if estimate_payload["available"]:
                cost_estimate = CostEstimate(
                    True,
                    hourly=Decimal(str(estimate_payload["fixed_hourly"])),
                    currency=str(estimate_payload["currency"]),
                    basis=str(estimate_payload["basis"]),
                )
        if isinstance(cost_estimate, CostEstimate) and cost_estimate.available:
            print(
                "estimated ongoing rate before destroy: "
                f"{format_money(cost_estimate.hourly, cost_estimate.currency)}/hour"
            )

    try:
        archive_mode = _select_archive_destroy_mode(ns, payload, env_name)
    except ValueError as exc:
        print(f"ERR: {exc}")
        record_destroy_outcome(
            "blocked",
            archive="not-selected",
            resources="retained",
        )
        print_destroy_record()
        return OPERATOR_ERROR

    if archive_mode == "cancel":
        print("destroy cancelled")
        print("environment retained")
        lifecycle = record_destroy_outcome(
            "cancelled",
            archive="not-started",
            resources="retained",
        )
        _print_destroy_lifecycle_summary(lifecycle)
        print_destroy_record()
        return CANCELLED

    if archive_mode == "keep":
        print("environment retained")
        lifecycle = record_destroy_outcome(
            "retained",
            archive="not-requested",
            resources="retained",
        )
        _print_destroy_lifecycle_summary(lifecycle)
        print_destroy_record()
        return 0

    if archive_mode == "archive":
        try:
            guest_quiesced = _confirm_guest_quiescence(ns, payload)
        except ValueError as exc:
            print(f"ERR: {exc}")
            record_destroy_outcome(
                "blocked",
                archive="not-started",
                resources="retained",
            )
            print_destroy_record()
            return OPERATOR_ERROR
        if guest_quiesced is not True:
            print("destroy cancelled")
            print("environment retained")
            lifecycle = record_destroy_outcome(
                "cancelled",
                archive="not-started",
                resources="retained",
            )
            _print_destroy_lifecycle_summary(lifecycle)
            print_destroy_record()
            return CANCELLED
        setattr(ns, "guest_quiesced", True)

    if not bool(getattr(ns, "yes", False)) and not json_mode:
        if payload.get("archive_before_destroy"):
            if _confirm_archive_destroy(env_name) is not True:
                print("destroy cancelled")
                print("environment retained")
                lifecycle = record_destroy_outcome(
                    "cancelled",
                    archive="not-started",
                    resources="retained",
                )
                _print_destroy_lifecycle_summary(lifecycle)
                print_destroy_record()
                return CANCELLED
        elif sys.stdin.isatty() and sys.stdout.isatty():
            confirmed = _prompt_yes_no("Proceed with blueprint destroy? [y/N]: ")
            if confirmed is None:
                lifecycle = record_destroy_outcome(
                    "cancelled",
                    archive="not-applicable",
                    resources="retained",
                )
                _print_destroy_lifecycle_summary(lifecycle)
                print_destroy_record()
                return CANCELLED
            if not confirmed:
                print("ERR: blueprint destroy cancelled by operator")
                lifecycle = record_destroy_outcome(
                    "cancelled",
                    archive="not-applicable",
                    resources="retained",
                )
                _print_destroy_lifecycle_summary(lifecycle)
                print_destroy_record()
                return OPERATOR_ERROR
        else:
            print("ERR: non-interactive blueprint destroy requires --yes")
            record_destroy_outcome(
                "blocked",
                archive="not-started",
                resources="retained",
            )
            print_destroy_record()
            return OPERATOR_ERROR

    archive_result = "skipped" if archive_mode == "skip" else "not-applicable"
    if archive_mode == "archive":
        archive_rc = _run_archive_before_destroy(ns, payload, paths)
        if archive_rc != 0:
            lifecycle = record_destroy_outcome(
                "archive-failed",
                archive="failed",
                resources="retained",
            )
            _print_destroy_lifecycle_summary(lifecycle)
            print_destroy_record()
            return archive_rc
        archive_result = "verified"

    fail_fast = bool(payload["policy"].get("fail_fast", True))
    step_results: list[dict[str, Any]] = []
    required_failures: list[str] = []
    optional_failures: list[str] = []
    cancelled = False
    progress = ProgressDisplay(
        enabled=bool(sys.stdout and sys.stdout.isatty() and not json_mode and not os.getenv("HYOPS_VERBOSE")),
        show_elapsed=False,
    )
    deferred_by_parent: dict[str, list[tuple[dict[str, Any], dict[str, Any]]]] = {}

    def finish_subsumed_steps(parent_id: str) -> list[str]:
        failures: list[str] = []
        for child_step, child_result in deferred_by_parent.pop(parent_id, []):
            child_ref, child_instance = split_module_state_ref(
                child_step["module_ref"],
                state_instance=child_step.get("state_instance") or None,
            )
            try:
                previous = read_module_state(
                    paths.state_dir,
                    child_ref,
                    state_instance=child_instance,
                )
            except FileNotFoundError:
                previous = {}
            except Exception as exc:
                child_result.update(
                    {
                        "status": "failed",
                        "rc": OPERATOR_ERROR,
                        "reason": f"failed to read deferred state: {exc}",
                    }
                )
                failures.append(child_step["id"])
                continue

            state_payload = dict(previous)
            state_payload.update(
                {
                    "module_ref": child_ref,
                    "status": "destroyed",
                    "updated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                    "outputs": {},
                    "output_count": 0,
                    "destroyed_by_blueprint_step": parent_id,
                }
            )
            for transient_key in (
                "active_command",
                "failed_command",
                "last_error",
                "mutation_started",
            ):
                state_payload.pop(transient_key, None)
            if child_instance:
                state_payload["state_instance"] = child_instance
            try:
                write_module_state(
                    paths.state_dir,
                    child_ref,
                    state_payload,
                    state_instance=child_instance,
                )
            except Exception as exc:
                child_result.update(
                    {
                        "status": "failed",
                        "rc": OPERATOR_ERROR,
                        "reason": f"parent was destroyed but child state update failed: {exc}",
                    }
                )
                failures.append(child_step["id"])
                continue
            child_result.update(
                {
                    "status": "subsumed",
                    "rc": 0,
                    "reason": f"destroyed with parent step {parent_id}",
                }
            )
        return failures

    total_steps = len(destroy_order)
    for step_position, step_id in enumerate(destroy_order, start=1):
        step = by_id[step_id]
        progress_before = int(((step_position - 1) * 100) / total_steps) if total_steps else 0
        progress_after = int((step_position * 100) / total_steps) if total_steps else 100
        running_label = f"{step_id}  stage {step_position}/{total_steps}"
        completed_detail = f"overall {progress_after}%"
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

        state_ref = step_state_ref(step)
        if bool(step.get("retain_on_destroy", False)):
            result = dict(base)
            result.update({"status": "retained", "reason": "retain_on_destroy", "rc": 0})
            step_results.append(result)
            progress.finish(
                step_id,
                step_id,
                "retained",
                plain=(f"step={step_id} status=retained reason=retain_on_destroy progress={progress_after}%"),
                detail=f"retain_on_destroy, {completed_detail}",
            )
            continue

        state_status = module_state_status(paths.state_dir, state_ref)
        destroy_gate_required = _destroy_gate_required(step, by_id, paths)
        if not destroy_gate_required and (not state_status or state_status in {"destroyed", "absent"}):
            reason = "no-state" if not state_status else f"state-{state_status}"
            result = dict(base)
            result.update({"status": "skipped", "reason": reason, "rc": 0})
            step_results.append(result)
            progress.finish(
                step_id,
                step_id,
                "skipped",
                plain=f"step={step_id} status=skipped reason={reason}",
                detail=f"{reason}, {completed_detail}",
            )
            if state_status in {"destroyed", "absent"}:
                required_failures.extend(finish_subsumed_steps(step_id))
            continue

        destroy_parent = str(step.get("destroy_subsumed_by") or "").strip()
        if destroy_parent:
            result = dict(base)
            result.update(
                {
                    "status": "deferred",
                    "reason": f"destroyed with parent step {destroy_parent}",
                    "rc": 0,
                }
            )
            step_results.append(result)
            deferred_by_parent.setdefault(destroy_parent, []).append((step, result))
            progress.finish(
                step_id,
                step_id,
                "deferred",
                plain=(f"step={step_id} status=deferred reason=destroy-subsumed-by-{destroy_parent}"),
                detail=f"awaiting {destroy_parent}, {completed_detail}",
            )
            continue

        # Materialize inputs only for a step that still has state to destroy.
        try:
            inputs_file = resolved_step_inputs_file(step, payload, paths)
        except Exception as exc:
            inputs_file = None
            print(f"step={step_id} WARN: failed to materialize inputs file: {exc}")
        else:
            if inputs_file:
                base["inputs_file"] = str(inputs_file)

        progress.start(
            step_id,
            running_label,
            plain=(f"step={step_id} status=running action=destroy module={step['module_ref']}"),
        )
        previous_child = os.environ.get("HYOPS_PROGRESS_CHILD")
        failure_state_before = _step_failure_state(destroy_step, paths)
        if not os.getenv("HYOPS_VERBOSE"):
            os.environ["HYOPS_PROGRESS_CHILD"] = "1"
        try:
            rc = run_step_module_command(destroy_step, payload, ns, paths)
        except KeyboardInterrupt:
            rc = CANCELLED
            err = "cancelled by user"
        except Exception as exc:
            rc = OPERATOR_ERROR
            err = format_runtime_storage_error(exc)
        else:
            err = ""
        finally:
            if previous_child is None:
                os.environ.pop("HYOPS_PROGRESS_CHILD", None)
            else:
                os.environ["HYOPS_PROGRESS_CHILD"] = previous_child

        if rc != 0 and not err:
            err = _new_step_failure_detail(
                destroy_step,
                paths,
                failure_state_before,
            )

        if rc == 0:
            result = dict(base)
            result.update({"status": "ok", "rc": 0})
            step_results.append(result)
            progress.finish(
                step_id,
                step_id,
                "ok",
                plain=f"step={step_id} status=ok progress={progress_after}%",
                detail=completed_detail,
            )
            required_failures.extend(finish_subsumed_steps(step_id))
            continue

        result = dict(base)
        result.update({"status": "failed", "rc": int(rc), "reason": err or "step command failed"})
        if int(rc) == CANCELLED:
            result["status"] = "cancelled"
            step_results.append(result)
            cancelled = True
            progress.finish(
                step_id,
                step_id,
                "cancelled",
                plain=f"step={step_id} status=cancelled rc={rc}",
                detail=f"overall {progress_before}%",
            )
            break
        if step["optional"]:
            result["status"] = "failed-optional"
            optional_failures.append(step_id)
            step_results.append(result)
            progress.finish(
                step_id,
                step_id,
                "failed-optional",
                plain=f"step={step_id} status=failed-optional rc={rc}",
                detail=completed_detail,
            )
            continue

        required_failures.append(step_id)
        step_results.append(result)
        failure_detail = err or "see module run record"
        progress.finish(
            step_id,
            step_id,
            "failed",
            plain=f"step={step_id} status=failed rc={rc} reason={failure_detail}",
            detail=f"overall {progress_before}%",
        )
        if progress.enabled and err:
            print(f"error: {failure_detail}", file=sys.stderr)
        if fail_fast:
            break

    for parent_id, pending in deferred_by_parent.items():
        for child_step, child_result in pending:
            child_result.update(
                {
                    "status": "failed",
                    "rc": OPERATOR_ERROR,
                    "reason": f"parent step {parent_id} was not confirmed destroyed",
                }
            )
            if child_step["id"] not in required_failures:
                required_failures.append(child_step["id"])

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
    cost_cleared = False
    if final_status == "ok" and str(payload["blueprint_ref"]).startswith("gcp/"):
        cost_cleared = _destroyed_blueprint_cost_cleared(payload, paths)
    resources_result = "released" if cost_cleared else "unverified"
    lifecycle = record_destroy_outcome(
        final_status,
        archive=archive_result,
        resources=resources_result,
        steps=step_results,
    )
    if lifecycle is not None:
        output["lifecycle"] = lifecycle
        estimate_payload = lifecycle["estimate"]
        output["cost"] = {
            "status": "cleared" if cost_cleared else "unverified",
            "estimated_ongoing_hourly": estimate_payload["ongoing_hourly"],
            "estimated_fixed_total": estimate_payload["fixed_total"],
            "currency": estimate_payload["currency"],
            "basis": estimate_payload["basis"],
            "scope": "declared blueprint resources",
        }
    if record_dir is not None:
        output["run_record"] = str(record_dir)

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
        if archive_result in {"verified", "skipped"}:
            print(f"lab preservation: {archive_result}")
        _print_destroy_lifecycle_summary(lifecycle)
        print_destroy_record()

    if cancelled:
        return CANCELLED
    return 0 if not required_failures else OPERATOR_ERROR


def run_rebuild(ns) -> int:
    if not bool(getattr(ns, "execute", False)) or bool(getattr(ns, "_lifecycle_lock_held", False)):
        return _run_rebuild_unlocked(ns)
    try:
        require_runtime_selection(
            getattr(ns, "root", None),
            getattr(ns, "env", None),
            command_label="hyops blueprint rebuild",
        )
        paths = resolve_runtime_paths(
            getattr(ns, "root", None),
            getattr(ns, "env", None),
        )
        ensure_layout(paths)
        with LifecycleLock(paths, "blueprint rebuild"):
            setattr(ns, "_lifecycle_lock_held", True)
            try:
                return _run_rebuild_unlocked(ns)
            finally:
                setattr(ns, "_lifecycle_lock_held", False)
    except (LifecycleBusy, OSError, ValueError) as exc:
        print(f"ERR: blueprint rebuild failed: {exc}")
        return OPERATOR_ERROR


def _run_rebuild_unlocked(ns) -> int:
    try:
        payload = _resolve_and_validate(ns)
    except Exception as exc:
        print(f"ERR: blueprint rebuild failed: {exc}")
        return OPERATOR_ERROR

    destroy_order = list(reversed(payload["order"]))
    print(
        f"blueprint={payload['blueprint_ref']} mode={payload['mode']} rebuild_steps={len(payload['order'])}"
    )
    if not bool(getattr(ns, "execute", False)) or verbose_enabled():
        print("destroy_order:")
        for step_id in destroy_order:
            step = next(s for s in payload["steps"] if s["id"] == step_id)
            suffix = " (retained)" if bool(step.get("retain_on_destroy", False)) else ""
            print(f"  - {_step_display_label(step)}{suffix}")
        print("deploy_order:")
        for step_id in payload["order"]:
            step = next(s for s in payload["steps"] if s["id"] == step_id)
            print(f"  - {_step_display_label(step)}")

    if not bool(getattr(ns, "execute", False)):
        return 0
    if bool(getattr(ns, "json", False)):
        print("ERR: --json is not supported with blueprint rebuild --execute")
        return OPERATOR_ERROR

    skip_preflight = bool(getattr(ns, "skip_preflight", False))
    try:
        preflight_bypass_reason = validate_preflight_bypass(
            command="rebuild",
            skip_preflight=skip_preflight,
            reason=getattr(ns, "preflight_bypass_reason", None),
        )
    except ValueError as exc:
        print(f"ERR: blueprint rebuild failed: {exc}")
        return OPERATOR_ERROR

    rebuild_preflight_decision = new_preflight_decision(
        command="rebuild",
        skip_preflight=skip_preflight,
        reason=preflight_bypass_reason,
        scope="blueprint",
    )

    try:
        require_runtime_selection(
            getattr(ns, "root", None),
            getattr(ns, "env", None),
            command_label="hyops blueprint rebuild",
        )
        paths = resolve_runtime_paths(getattr(ns, "root", None), getattr(ns, "env", None))
        ensure_layout(paths)
    except Exception as exc:
        print(f"ERR: blueprint rebuild failed: {exc}")
        return OPERATOR_ERROR

    env_name = str(getattr(ns, "env", None) or paths.root.name).strip()
    if not bool(getattr(ns, "yes", False)):
        print(f"WARN: blueprint rebuild will destroy and recreate owned resources in env={env_name}.")
        if not (sys.stdin.isatty() and sys.stdout.isatty()):
            print("ERR: non-interactive rebuild requires --yes")
            return OPERATOR_ERROR
        confirmed = _prompt_yes_no("Proceed with blueprint rebuild? [y/N]: ")
        if confirmed is None:
            return CANCELLED
        if not confirmed:
            print("ERR: blueprint rebuild cancelled by operator")
            return CANCELLED

    token = re.sub(r"[^A-Za-z0-9_.-]+", "_", payload["blueprint_ref"])
    run_id = new_run_id("rebuild")
    record_dir = paths.logs_dir / "blueprint" / token / run_id
    record_dir.mkdir(parents=True, exist_ok=True)
    record_file = record_dir / "rebuild.json"
    record_writer = EvidenceWriter(record_dir)

    def write_record(status: str, destroy_rc: int | None, deploy_rc: int | None) -> None:
        record_writer.write_json(
            record_file.name,
            {
                "blueprint_ref": payload["blueprint_ref"],
                "env": env_name,
                "run_id": run_id,
                "status": status,
                "destroy_order": destroy_order,
                "deploy_order": payload["order"],
                "destroy_rc": destroy_rc,
                "deploy_rc": deploy_rc,
                "preflight": rebuild_preflight_decision,
            },
        )

    write_record("running", None, None)
    child_args = dict(vars(ns))
    child_args.update(
        {
            "yes": True,
            "json": False,
            "execute": True,
            "archive_before_destroy": False,
            "skip_archive": bool(payload.get("archive_before_destroy")),
            "preflight_bypass_reason": preflight_bypass_reason,
        }
    )
    print("rebuild_phase=destroy status=running")
    destroy_rc = int(run_destroy(argparse.Namespace(**child_args)))
    if destroy_rc != 0:
        write_record("destroy-failed", destroy_rc, None)
        print("rebuild_phase=deploy status=skipped reason=destroy-failed")
        print(f"run record: {record_dir}")
        return destroy_rc

    print("rebuild_phase=destroy status=ok")
    print("rebuild_phase=deploy status=running")
    deploy_ns = argparse.Namespace(**child_args)
    deploy_rc = int(run_deploy(deploy_ns))
    deploy_preflight = getattr(deploy_ns, "preflight_context", None)
    if isinstance(deploy_preflight, dict):
        rebuild_preflight_decision = dict(deploy_preflight)
    final_status = "ok" if deploy_rc == 0 else "deploy-failed"
    write_record(final_status, destroy_rc, deploy_rc)
    print(f"rebuild_phase=deploy status={'ok' if deploy_rc == 0 else 'failed'}")
    print(f"blueprint={payload['blueprint_ref']} rebuild_status={final_status}")
    print(f"run record: {record_dir}")
    return deploy_rc


__all__ = [
    "add_blueprint_subparser",
    "run_validate",
    "run_preflight",
    "run_plan",
    "run_session",
    "run_deploy",
    "run_destroy",
    "run_rebuild",
]
