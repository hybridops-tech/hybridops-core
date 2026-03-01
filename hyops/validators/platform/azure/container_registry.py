"""Validate inputs for module platform/azure/container-registry."""

from __future__ import annotations

from typing import Any
import re

from hyops.validators.registry import ModuleValidationError


_SLUG_RE = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,38}[a-z0-9])?$")
_ACR_NAME_RE = re.compile(r"^[a-z0-9]{5,50}$")


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

    def req_bool(key: str) -> bool:
        value = inputs.get(key)
        if not isinstance(value, bool):
            raise ModuleValidationError(f"inputs.{key} must be a boolean")
        return value

    def opt_dict(key: str) -> dict[str, Any]:
        value = inputs.get(key)
        if value is None:
            return {}
        if not isinstance(value, dict):
            raise ModuleValidationError(f"inputs.{key} must be a mapping when set")
        return value

    _ = req_str("resource_group_name")
    _ = req_str("location")

    name_prefix = opt_str("name_prefix")
    context_id = opt_str("context_id")
    registry_name = opt_str("registry_name")

    if name_prefix and not _SLUG_RE.fullmatch(name_prefix):
        raise ModuleValidationError("inputs.name_prefix must match [a-z0-9-] and start/end alnum")
    if context_id and not _SLUG_RE.fullmatch(context_id):
        raise ModuleValidationError("inputs.context_id must match [a-z0-9-] and start/end alnum")

    if registry_name and not _ACR_NAME_RE.fullmatch(registry_name):
        raise ModuleValidationError("inputs.registry_name must be lowercase alphanumeric, 5-50 chars")

    sku = req_str("sku")
    if sku not in {"Basic", "Standard", "Premium"}:
        raise ModuleValidationError("inputs.sku must be one of: Basic, Standard, Premium")

    _ = req_bool("admin_enabled")
    _ = req_bool("public_network_access_enabled")
    zone_redundancy_enabled = req_bool("zone_redundancy_enabled")

    if zone_redundancy_enabled and sku != "Premium":
        raise ModuleValidationError("inputs.zone_redundancy_enabled requires inputs.sku=Premium")

    tags = opt_dict("tags")
    for key, value in tags.items():
        if not isinstance(key, str) or not key.strip():
            raise ModuleValidationError("inputs.tags keys must be non-empty strings")
        if not isinstance(value, str):
            raise ModuleValidationError("inputs.tags values must be strings")
