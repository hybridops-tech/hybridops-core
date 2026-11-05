"""Validate inputs for platform/linux/gns3-server module."""

from __future__ import annotations

from typing import Any

from hyops.validators.registry import ModuleValidationError


def validate(inputs: dict[str, Any]) -> None:
    allowed = {
        "gns3_port",
        "gns3_projects_dir",
        "_hyops_lifecycle_command",
        "_hyops_invocation_command",
    }
    unknown = sorted(str(key) for key in inputs if str(key) not in allowed)
    if unknown:
        raise ModuleValidationError(f"unknown inputs: {', '.join(unknown)}")
