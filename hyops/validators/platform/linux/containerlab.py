"""Validate inputs for platform/linux/containerlab module."""

from __future__ import annotations

from typing import Any

from hyops.validators.registry import ModuleValidationError


def validate(inputs: dict[str, Any]) -> None:
    allowed = {
        "containerlab_dir",
        "lab_name",
        "_hyops_lifecycle_command",
        "_hyops_invocation_command",
    }
    unknown = sorted(str(key) for key in inputs if str(key) not in allowed)
    if unknown:
        raise ModuleValidationError(f"unknown inputs: {', '.join(unknown)}")
