"""Validate inputs for core/local/quickstart."""

from __future__ import annotations

import re
from typing import Any

from hyops.validators.registry import ModuleValidationError


_OPERATION_ID = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")


def validate(inputs: dict[str, Any]) -> None:
    allowed = {
        "operation_id",
        "declared_outcome",
        "_hyops_lifecycle_command",
        "_hyops_invocation_command",
    }
    unknown = sorted(str(key) for key in inputs if str(key) not in allowed)
    if unknown:
        raise ModuleValidationError(f"unknown inputs: {', '.join(unknown)}")

    operation_id = inputs.get("operation_id")
    if not isinstance(operation_id, str) or not _OPERATION_ID.fullmatch(operation_id):
        raise ModuleValidationError(
            "inputs.operation_id must be a lowercase identifier of up to 64 characters"
        )

    outcome = inputs.get("declared_outcome")
    if not isinstance(outcome, str) or not outcome.strip():
        raise ModuleValidationError("inputs.declared_outcome must be a non-empty string")
    if len(outcome) > 120 or any(ord(char) < 32 for char in outcome):
        raise ModuleValidationError(
            "inputs.declared_outcome must be printable and 120 characters or fewer"
        )
