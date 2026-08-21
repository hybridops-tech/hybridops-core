"""Preflight enforcement and audit records for governed execution."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Mapping


MUTATING_COMMANDS = frozenset({"apply", "deploy", "destroy", "import", "rebuild"})
MAX_BYPASS_REASON_LENGTH = 500


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def validate_preflight_bypass(
    *,
    command: str,
    skip_preflight: bool,
    reason: str | None,
) -> str:
    """Validate a preflight bypass request and return its normalized reason."""

    command_name = str(command or "").strip().lower()
    normalized = str(reason or "").strip()

    if normalized and not skip_preflight:
        raise ValueError("--preflight-bypass-reason requires --skip-preflight")
    if any(ord(char) < 32 or ord(char) == 127 for char in normalized):
        raise ValueError("--preflight-bypass-reason must be a single printable line")
    if len(normalized) > MAX_BYPASS_REASON_LENGTH:
        raise ValueError(
            "--preflight-bypass-reason must not exceed "
            f"{MAX_BYPASS_REASON_LENGTH} characters"
        )
    if skip_preflight and command_name in MUTATING_COMMANDS and not normalized:
        raise ValueError(
            "--skip-preflight for a mutating command requires "
            "--preflight-bypass-reason"
        )
    return normalized


def new_preflight_decision(
    *,
    command: str,
    skip_preflight: bool,
    reason: str = "",
    scope: str = "driver",
    decision_source: str = "operator-cli",
    parent: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Create the record written before a command can cross its preflight boundary."""

    bypassed = bool(skip_preflight)
    decision: dict[str, Any] = {
        "schema_version": 1,
        "scope": str(scope or "driver").strip(),
        "requirement": f"{str(scope or 'driver').strip()}-preflight",
        "command": str(command or "").strip().lower(),
        "mutating": str(command or "").strip().lower() in MUTATING_COMMANDS,
        "decision": "bypass" if bypassed else "enforce",
        "status": "bypassed" if bypassed else "pending",
        "guarantee": "not-established" if bypassed else "pending",
        "decision_source": str(decision_source or "operator-cli").strip(),
        "reason": str(reason or "").strip(),
        "recorded_at": _utc_now(),
    }
    if parent:
        decision["parent"] = dict(parent)
    return decision


def complete_preflight_decision(
    decision: Mapping[str, Any],
    *,
    passed: bool,
    detail: str = "",
) -> dict[str, Any]:
    """Return a completed copy of an enforced preflight decision."""

    completed = dict(decision)
    completed["status"] = "passed" if passed else "failed"
    completed["guarantee"] = "established" if passed else "not-established"
    completed["completed_at"] = _utc_now()
    if detail:
        completed["detail"] = str(detail).strip()
    return completed
