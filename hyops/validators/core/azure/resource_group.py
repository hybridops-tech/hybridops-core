"""Validate inputs for module core/azure/resource-group."""

from __future__ import annotations

from typing import Any
import re

from hyops.validators.registry import ModuleValidationError


_SLUG_RE = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,38}[a-z0-9])?$")


def validate(inputs: dict[str, Any]) -> None:
    def req_str(key: str) -> str:
        value = inputs.get(key)
        if not isinstance(value, str) or not value.strip():
            raise ModuleValidationError(f"inputs.{key} must be a non-empty string")
        return value.strip()

    def opt_str(key: str) -> str:
        value = inputs.get(key)
        if value is None:
            return ""
        if not isinstance(value, str):
            raise ModuleValidationError(f"inputs.{key} must be a string when set")
        return value.strip()

    def opt_dict(key: str) -> dict[str, Any]:
        value = inputs.get(key)
        if value is None:
            return {}
        if not isinstance(value, dict):
            raise ModuleValidationError(f"inputs.{key} must be a mapping when set")
        return value

    location = req_str("location")
    name_prefix = opt_str("name_prefix")
    context_id = opt_str("context_id")
    resource_group_name = opt_str("resource_group_name")
    tags = opt_dict("tags")

    if name_prefix and not _SLUG_RE.fullmatch(name_prefix):
        raise ModuleValidationError("inputs.name_prefix must match [a-z0-9-] and start/end alnum")
    if context_id and not _SLUG_RE.fullmatch(context_id):
        raise ModuleValidationError("inputs.context_id must match [a-z0-9-] and start/end alnum")

    if resource_group_name and len(resource_group_name) > 90:
        raise ModuleValidationError("inputs.resource_group_name must be 90 characters or fewer")

    if location and len(location) > 64:
        raise ModuleValidationError("inputs.location looks invalid")

    for key, value in tags.items():
        if not isinstance(key, str) or not key.strip():
            raise ModuleValidationError("inputs.tags keys must be non-empty strings")
        if not isinstance(value, str):
            raise ModuleValidationError("inputs.tags values must be strings")
