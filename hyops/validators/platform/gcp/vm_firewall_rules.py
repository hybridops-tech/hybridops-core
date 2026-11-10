"""Validate inputs for platform/gcp/vm-firewall-rules module."""

from __future__ import annotations

from typing import Any

from hyops.validators.registry import ModuleValidationError


def validate(inputs: dict[str, Any]) -> None:
    allowed = {
        '_hyops_invocation_command',
        '_hyops_lifecycle_command',
        'context_id',
        'name_prefix',
        'network',
        'project_id',
        'rules'
    }
    unknown = sorted(str(key) for key in inputs if str(key) not in allowed)
    if unknown:
        raise ModuleValidationError(f"unknown inputs: {", ".join(unknown)}")