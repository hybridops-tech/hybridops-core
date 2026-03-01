"""Playbook selection helpers for the Ansible config driver."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def read_module_state_status(runtime_root: Path, module_id: str) -> str:
    path = (runtime_root / "state" / "modules" / module_id / "latest.json").resolve()
    if not path.exists():
        return ""
    try:
        payload = json.loads(path.read_text(encoding="utf-8")) or {}
    except Exception:
        return ""
    if not isinstance(payload, dict):
        return ""
    return str(payload.get("status") or "").strip().lower()


def list_playbook_modes(pack_stack: Path) -> list[str]:
    out: set[str] = set()
    for item in pack_stack.glob("playbook.*.yml"):
        name = item.name
        if not name.startswith("playbook.") or not name.endswith(".yml"):
            continue
        mode = name[len("playbook.") : -len(".yml")].strip().lower()
        if mode:
            out.add(mode)
    return sorted(out)


def resolve_playbook_file(
    *,
    command_name: str,
    ansible_cfg: dict[str, Any],
    inputs: dict[str, Any],
    runtime_root: Path,
    module_id: str,
    pack_stack: Path,
) -> tuple[str, str, str]:
    """Resolve which playbook file to run.

    Supports optional multi-entrypoint packs via inputs.apply_mode:
    - bootstrap: use profile playbook_file (default: playbook.yml)
    - <mode>: use playbook.<mode>.yml when present in the pack stack
    - auto: when playbook.maintenance.yml exists and prior module state status is ok, use maintenance
    """

    default_playbook = str(ansible_cfg.get("playbook_file") or "playbook.yml").strip() or "playbook.yml"
    destroy_playbook = str(ansible_cfg.get("destroy_playbook_file") or "destroy.playbook.yml").strip() or "destroy.playbook.yml"

    if command_name == "destroy":
        destroy_path = (pack_stack / destroy_playbook).resolve()
        if not destroy_path.exists():
            return "", "", f"destroy not supported for this pack (missing {destroy_playbook})"
        return destroy_playbook, "", ""

    raw_mode = str(inputs.get("apply_mode") or "").strip().lower()
    if not raw_mode:
        return default_playbook, "", ""

    mode = raw_mode
    if mode in ("bootstrap", "deploy"):
        return default_playbook, f"apply_mode={mode} (using {default_playbook})", ""

    if mode == "auto":
        candidate = (pack_stack / "playbook.maintenance.yml").resolve()
        if not candidate.exists():
            return default_playbook, "apply_mode=auto (maintenance entrypoint not present; using bootstrap)", ""
        prior_status = read_module_state_status(runtime_root, module_id)
        if prior_status in ("ok", "ready"):
            return "playbook.maintenance.yml", f"apply_mode=auto selected maintenance (prior state status={prior_status})", ""
        suffix = prior_status or "absent"
        return default_playbook, f"apply_mode=auto selected bootstrap (prior state status={suffix})", ""

    candidate_file = f"playbook.{mode}.yml"
    candidate_path = (pack_stack / candidate_file).resolve()
    if candidate_path.exists():
        return candidate_file, f"apply_mode={mode} (using {candidate_file})", ""

    available = list_playbook_modes(pack_stack)
    available_hint = ""
    if available:
        available_hint = "available apply_mode values: " + ", ".join(available) + ". "
    return (
        "",
        "",
        f"apply_mode={mode!r} requested but playbook not found: {candidate_file}. {available_hint}"
        f"Use apply_mode=bootstrap to run {default_playbook}.",
    )
