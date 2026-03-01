"""Validate inputs for module core/azure/vnet."""

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

    def req_list_of_str(key: str) -> list[str]:
        value = inputs.get(key)
        if not isinstance(value, list) or not value:
            raise ModuleValidationError(f"inputs.{key} must be a non-empty list")
        out: list[str] = []
        for item in value:
            if not isinstance(item, str) or not item.strip():
                raise ModuleValidationError(f"inputs.{key} entries must be non-empty strings")
            out.append(item.strip())
        return out

    def opt_list_of_str(key: str) -> list[str]:
        value = inputs.get(key)
        if value is None:
            return []
        if not isinstance(value, list):
            raise ModuleValidationError(f"inputs.{key} must be a list when set")
        out: list[str] = []
        for item in value:
            if not isinstance(item, str) or not item.strip():
                raise ModuleValidationError(f"inputs.{key} entries must be non-empty strings")
            out.append(item.strip())
        return out

    def opt_dict(key: str) -> dict[str, Any]:
        value = inputs.get(key)
        if value is None:
            return {}
        if not isinstance(value, dict):
            raise ModuleValidationError(f"inputs.{key} must be a mapping when set")
        return value

    _ = req_str("location")
    _ = req_str("resource_group_name")

    name_prefix = opt_str("name_prefix")
    context_id = opt_str("context_id")
    vnet_name = opt_str("vnet_name")

    if name_prefix and not _SLUG_RE.fullmatch(name_prefix):
        raise ModuleValidationError("inputs.name_prefix must match [a-z0-9-] and start/end alnum")
    if context_id and not _SLUG_RE.fullmatch(context_id):
        raise ModuleValidationError("inputs.context_id must match [a-z0-9-] and start/end alnum")
    if vnet_name and len(vnet_name) > 80:
        raise ModuleValidationError("inputs.vnet_name must be 80 characters or fewer")

    address_space = req_list_of_str("address_space")
    for cidr in address_space:
        if "/" not in cidr:
            raise ModuleValidationError("inputs.address_space must contain CIDR entries")

    _ = opt_list_of_str("dns_servers")

    tags = opt_dict("tags")
    for key, value in tags.items():
        if not isinstance(key, str) or not key.strip():
            raise ModuleValidationError("inputs.tags keys must be non-empty strings")
        if not isinstance(value, str):
            raise ModuleValidationError("inputs.tags values must be strings")
