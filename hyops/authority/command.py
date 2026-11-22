"""Operator commands for authority providers and continuity evidence."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from collections.abc import Mapping
from datetime import datetime
from pathlib import Path
from typing import Any

from hyops.runtime.exitcodes import OPERATOR_ERROR

from .models import AUTHORITY_PROVIDER_CONTRACT_VERSION
from .resolver import default_authority_registry, interval_decision

_MAX_RECORD_BYTES = 16 * 1024 * 1024
_CONTROL_CHARACTER_RE = re.compile(r"[\x00-\x1f\x7f]+")
_MAX_TEXT_LENGTH = 500
_RUN_STATUSES = frozenset({"ok", "failed", "cancelled"})
_STEP_STATUSES = frozenset({"ok", "failed", "cancelled", "skipped", "blocked"})
_IDENTITY_FIELDS = (
    "source",
    "distribution",
    "version",
    "entry_point",
    "contract_version",
)


def _provider_inventory() -> list[dict[str, Any]]:
    registry = default_authority_registry()
    registry.require_discovery_complete()
    return [
        {
            "name": name,
            "capabilities": sorted(registry.registration(name).capabilities),
            "identity": registry.registration(name).identity.to_evidence(),
        }
        for name in registry.names()
    ]


def run_providers(ns: argparse.Namespace) -> int:
    try:
        providers = _provider_inventory()
    except (RuntimeError, TypeError, ValueError) as exc:
        print(f"ERR: authority provider inventory failed: {exc}", file=sys.stderr)
        return OPERATOR_ERROR
    if bool(ns.json):
        print(json.dumps({"providers": providers}, indent=2, sort_keys=True))
        return 0
    print("authority providers:")
    for provider in providers:
        capabilities = ", ".join(provider["capabilities"]) or "none"
        identity = provider["identity"]
        print(
            f"  {provider['name']}: {capabilities} "
            f"[{identity['distribution']} {identity['version']}; "
            f"{identity['source']}]"
        )
    return 0


def _load_run_record(raw_path: str) -> tuple[dict[str, Any], str]:
    path = Path(raw_path).expanduser().resolve()
    if not path.is_file():
        raise ValueError(f"run record does not exist: {path}")
    if path.stat().st_size > _MAX_RECORD_BYTES:
        raise ValueError("run record exceeds the 16 MiB inspection limit")
    try:
        with path.open("rb") as handle:
            content = handle.read(_MAX_RECORD_BYTES + 1)
        if len(content) > _MAX_RECORD_BYTES:
            raise ValueError("run record exceeds the 16 MiB inspection limit")
        payload = json.loads(content.decode("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"run record is not valid JSON: {exc}") from exc
    if not isinstance(payload, dict):
        raise TypeError("run record must contain a JSON object")
    return payload, hashlib.sha256(content).hexdigest()


def _required_text(
    payload: Mapping[str, Any],
    field: str,
    label: str,
) -> str:
    value = payload.get(field)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} {field} must be a non-empty string")
    if value != value.strip() or _CONTROL_CHARACTER_RE.search(value):
        raise ValueError(f"{label} {field} is not canonical text")
    if len(value) > _MAX_TEXT_LENGTH:
        raise ValueError(f"{label} {field} exceeds the inspection limit")
    return value


def _required_observation_token(payload: Mapping[str, Any], label: str) -> str:
    value = payload.get("token")
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} token must be a non-empty string")
    return value


def _provider_identity(payload: Mapping[str, Any], label: str) -> dict[str, str]:
    raw_identity = payload.get("provider_identity")
    if not isinstance(raw_identity, Mapping):
        raise TypeError(f"{label} provider_identity must be an object")
    identity = {
        field: _required_text(raw_identity, field, f"{label} provider_identity")
        for field in _IDENTITY_FIELDS
    }
    if identity["contract_version"] != AUTHORITY_PROVIDER_CONTRACT_VERSION:
        raise ValueError(
            f"{label} uses unsupported authority provider contract version"
        )
    return identity


def _validate_observation(payload: Any, label: str) -> datetime | None:
    if payload is None:
        return None
    if not isinstance(payload, Mapping):
        raise TypeError(f"{label} must be an object")
    _required_observation_token(payload, label)
    for field in ("observed_at", "scope", "strength"):
        _required_text(payload, field, label)
    observed_at = str(payload["observed_at"])
    try:
        timestamp = datetime.fromisoformat(observed_at)
    except ValueError as exc:
        raise ValueError(f"{label} observed_at must be an ISO-8601 timestamp") from exc
    if timestamp.tzinfo is None:
        raise ValueError(f"{label} observed_at must include a UTC offset")
    metadata = payload.get("metadata")
    if metadata is not None and not isinstance(metadata, Mapping):
        raise ValueError(f"{label} metadata must be an object")
    return timestamp


def _validated_step(step: Mapping[str, Any]) -> tuple[str, str]:
    step_id = _required_text(step, "id", "run record step")
    step_status = _required_text(step, "status", f"step '{step_id}'")
    if step_status not in _STEP_STATUSES:
        raise ValueError(f"step '{step_id}' status is invalid")
    return step_id, step_status


def _validated_authority_outcome(
    step_id: str,
    step_status: str,
    admission: Mapping[str, Any],
    interval: Mapping[str, Any],
) -> dict[str, str]:
    if not admission:
        raise ValueError(f"step '{step_id}' interval evidence lacks admission evidence")

    label = f"step '{step_id}' authority admission"
    logical_authority = _required_text(admission, "logical_authority", label)
    provider = _required_text(admission, "provider", label)
    capability = _required_text(admission, "capability", label)
    admission_state = _required_text(admission, "verified_state", label)
    admission_result = _required_text(admission, "result", label)
    identity = _provider_identity(admission, label)
    admission_observation = admission.get("observation")
    _validate_observation(admission_observation, f"{label} observation")

    outcome = {
        "step": step_id,
        "step_status": step_status,
        "logical_authority": logical_authority,
        "provider": provider,
        "provider_source": identity["source"],
        "provider_distribution": identity["distribution"],
        "provider_version": identity["version"],
        "provider_contract_version": identity["contract_version"],
        "capability": capability,
        "admission_state": admission_state,
        "interval_status": "",
        "completion_status": "",
        "decision": "",
        "expected_change": "",
        "detection_strength": "",
        "result": admission_result,
    }
    if not interval:
        return outcome

    interval_label = f"step '{step_id}' authority interval"
    for field, admission_value in (
        ("logical_authority", logical_authority),
        ("provider", provider),
        ("capability", capability),
    ):
        if _required_text(interval, field, interval_label) != admission_value:
            raise ValueError(
                f"{interval_label} {field} does not match admission evidence"
            )
    if _provider_identity(interval, interval_label) != identity:
        raise ValueError(
            f"{interval_label} provider identity does not match admission evidence"
        )

    interval_status = _required_text(interval, "interval_status", interval_label)
    completion_status = _required_text(interval, "completion_status", interval_label)
    on_unverifiable = _required_text(interval, "on_unverifiable", interval_label)
    decision = _required_text(interval, "decision", interval_label)
    expected_decision = interval_decision(
        interval_status,
        completion_status,
        on_unverifiable,
    )
    # Provider failures may force a stricter fail-closed decision.
    if decision != expected_decision and not (
        decision == "deny" and expected_decision == "record"
    ):
        raise ValueError(f"{interval_label} decision contradicts the runtime policy")
    if step_status == "ok" and decision == "deny":
        raise ValueError(f"step '{step_id}' is ok but its authority decision is deny")
    expected_change = _required_text(interval, "expected_change", interval_label)
    if expected_change not in {"none", "operation"}:
        raise ValueError(f"{interval_label} expected_change is invalid")
    detection_strength = _required_text(interval, "detection_strength", interval_label)
    result = _required_text(interval, "result", interval_label)
    _required_text(interval, "freshness_basis", interval_label)
    before = interval.get("before")
    after = interval.get("after")
    before_time = _validate_observation(before, f"{interval_label} before")
    after_time = _validate_observation(after, f"{interval_label} after")
    if before != admission_observation:
        raise ValueError(
            f"{interval_label} before observation does not match admission evidence"
        )
    if interval_status in {"stable", "drifted"} and (
        not isinstance(before, Mapping) or not isinstance(after, Mapping)
    ):
        raise ValueError(f"{interval_label} requires before and after observations")
    if isinstance(before, Mapping) and isinstance(after, Mapping):
        if interval_status in {"stable", "drifted"} and before.get(
            "scope"
        ) != after.get("scope"):
            raise ValueError(f"{interval_label} observation scope changed")
        if (
            completion_status != "stale"
            and before_time is not None
            and after_time is not None
            and after_time < before_time
        ):
            raise ValueError(f"{interval_label} after observation predates admission")

    outcome.update(
        {
            "interval_status": interval_status,
            "completion_status": completion_status,
            "decision": decision,
            "expected_change": expected_change,
            "detection_strength": detection_strength,
            "result": result,
        }
    )
    return outcome


def _authority_outcomes(record: Mapping[str, Any]) -> list[dict[str, str]]:
    steps = record.get("steps")
    if not isinstance(steps, list):
        raise TypeError("run record steps must be a list")
    outcomes = []
    for step in steps:
        if not isinstance(step, Mapping):
            raise TypeError("run record contains an invalid step")
        step_id, step_status = _validated_step(step)
        raw_admission = step.get("authority")
        raw_interval = step.get("authority_interval")
        if raw_admission is not None and not isinstance(raw_admission, Mapping):
            raise TypeError("run record contains invalid authority admission evidence")
        if raw_interval is not None and not isinstance(raw_interval, Mapping):
            raise TypeError("run record contains invalid authority interval evidence")
        admission = raw_admission or {}
        interval = raw_interval or {}
        if not admission and not interval:
            continue
        outcomes.append(
            _validated_authority_outcome(
                step_id,
                step_status,
                admission,
                interval,
            )
        )
    return outcomes


def _inspection_payload(
    record: Mapping[str, Any], record_sha256: str
) -> dict[str, Any]:
    status = _required_text(record, "status", "run record")
    if status not in _RUN_STATUSES:
        raise ValueError("run record status is invalid")
    return {
        "blueprint_ref": _required_text(record, "blueprint_ref", "run record"),
        "run_id": _required_text(record, "run_id", "run record"),
        "status": status,
        "record_sha256": record_sha256,
        "validation": "schema-and-policy-consistent",
        "record_authenticity": "not-verified",
        "authority_outcomes": _authority_outcomes(record),
    }


def run_inspect(ns: argparse.Namespace) -> int:
    try:
        record, record_sha256 = _load_run_record(str(ns.record or ""))
        payload = _inspection_payload(record, record_sha256)
    except (OSError, TypeError, ValueError) as exc:
        print(f"ERR: authority inspection failed: {exc}", file=sys.stderr)
        return OPERATOR_ERROR
    if bool(ns.json):
        print(json.dumps(payload, indent=2, sort_keys=True))
        return 0
    print(
        f"authority continuity: blueprint={payload['blueprint_ref'] or 'unknown'} "
        f"run={payload['run_id'] or 'unknown'} "
        f"status={payload['status'] or 'unknown'} "
        f"validation={payload['validation']} "
        f"authenticity={payload['record_authenticity']}"
    )
    outcomes = payload["authority_outcomes"]
    if not outcomes:
        print("  outcomes: none")
        return 0
    for outcome in outcomes:
        print(
            f"  step={outcome['step'] or 'unknown'} "
            f"authority={outcome['logical_authority'] or 'unknown'} "
            f"provider={outcome['provider'] or 'unknown'} "
            f"interval={outcome['interval_status'] or 'not-observed'} "
            f"decision={outcome['decision'] or 'admission-only'}"
        )
    return 0


def add_authority_subparser(commands: argparse._SubParsersAction) -> None:
    parser = commands.add_parser(
        "authority",
        help="Inspect authority providers and continuity evidence.",
    )
    subcommands = parser.add_subparsers(dest="authority_cmd", required=True)

    providers = subcommands.add_parser(
        "providers",
        help="List registered authority providers and capabilities.",
    )
    providers.add_argument("--json", action="store_true", help="Emit JSON output.")
    providers.set_defaults(_handler=run_providers)

    inspect = subcommands.add_parser(
        "inspect",
        help="Show safe authority outcomes from a HybridOps run record.",
    )
    inspect.add_argument("--record", required=True, help="Path to a deploy run record.")
    inspect.add_argument("--json", action="store_true", help="Emit JSON output.")
    inspect.set_defaults(_handler=run_inspect)


__all__ = ["add_authority_subparser", "run_inspect", "run_providers"]
