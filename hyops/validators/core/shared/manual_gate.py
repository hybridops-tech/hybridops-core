"""hyops.validators.core.shared.manual_gate

purpose: Validate inputs for core/shared/manual-gate.
maintainer: HybridOps.Tech
"""

from __future__ import annotations

from typing import Any

from hyops.validators.common import (
    normalize_lifecycle_command,
    require_bool,
    require_mapping,
    require_non_empty_str,
)


def validate(inputs: dict[str, Any]) -> None:
    data = require_mapping(inputs, "inputs")
    lifecycle = normalize_lifecycle_command(data)
    invocation = str(data.get("_hyops_invocation_command") or "").strip().lower()

    require_non_empty_str(data.get("gate_name"), "inputs.gate_name")
    require_non_empty_str(data.get("gate_message"), "inputs.gate_message")

    confirm = require_bool(data.get("confirm"), "inputs.confirm")
    enforce_confirmation = invocation not in {"validate", "preflight", "plan"} and lifecycle != "destroy"
    if enforce_confirmation and not confirm:
        raise ValueError("inputs.confirm must be true (explicit operator confirmation required)")

    assertions = data.get("assertions")
    if assertions is None:
        assertions = {}
    if not isinstance(assertions, dict):
        raise ValueError("inputs.assertions must be a mapping when set")
    for key, value in assertions.items():
        require_non_empty_str(key, f"inputs.assertions[{key!r}]")
        current = require_bool(value, f"inputs.assertions[{key!r}]")
        if enforce_confirmation and not current:
            raise ValueError(
                f"inputs.assertions[{key!r}] must be true "
                f"(manual gate {data.get('gate_name')!r} is not fully acknowledged)"
            )

    notes = data.get("evidence_notes")
    if notes is None:
        notes = []
    if not isinstance(notes, list):
        raise ValueError("inputs.evidence_notes must be a list when set")
    for idx, item in enumerate(notes, start=1):
        require_non_empty_str(item, f"inputs.evidence_notes[{idx}]")
