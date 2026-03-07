"""Result parsing helpers for the Ansible config driver."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def ansible_error_hint(
    *,
    command_name: str,
    module_ref: str,
    inputs: dict[str, Any],
    evidence_dir: Path,
    label: str,
) -> str:
    if command_name != "apply":
        return ""

    chunks: list[str] = []
    for name in (f"{label}.stdout.txt", f"{label}.stderr.txt"):
        path = (evidence_dir / name).resolve()
        if not path.exists():
            continue
        try:
            data = path.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue
        if data:
            chunks.append(data[-20000:])
    tail = "\n".join(chunks).lower()
    if not tail:
        return ""

    if "data directory" in tail and "already initialized" in tail:
        if module_ref.strip().lower() in {"platform/postgresql-ha", "platform/onprem/postgresql-ha"} and str(inputs.get("apply_mode") or "").strip().lower() in ("", "auto", "bootstrap"):
            return (
                "postgresql-ha bootstrap detected existing initialized data directories. "
                "This usually means a prior bootstrap partially completed. "
                "Re-run with `inputs.apply_mode=maintenance`, or run `hyops destroy` for this module and bootstrap again."
            )
        return (
            "remote PostgreSQL data directories are already initialized. "
            "Use the module maintenance path for in-place reconciliation, or clean hosts before bootstrap."
        )

    return ""


def load_outputs(path: Path) -> dict[str, Any]:
    if not path.exists() or not path.is_file():
        return {}

    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}

    if not isinstance(payload, dict):
        return {}

    return payload
