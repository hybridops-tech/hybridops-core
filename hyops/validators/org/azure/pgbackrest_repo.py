"""Validate inputs for module org/azure/pgbackrest-repo."""

from __future__ import annotations

import re
from typing import Any

from hyops.validators.registry import ModuleValidationError


_SLUG_RE = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,38}[a-z0-9])?$")
_STORAGE_ACCOUNT_RE = re.compile(r"^[a-z0-9]{3,24}$")
_CONTAINER_RE = re.compile(r"^[a-z0-9](?:[a-z0-9-]{1,61}[a-z0-9])?$")


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

    def opt_bool(key: str) -> None:
        value = inputs.get(key)
        if value is None:
            return
        if not isinstance(value, bool):
            raise ModuleValidationError(f"inputs.{key} must be a boolean when set")

    def opt_num(key: str) -> float:
        value = inputs.get(key)
        if value is None:
            return 0.0
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ModuleValidationError(f"inputs.{key} must be a number when set")
        return float(value)

    def opt_dict(key: str) -> dict[str, Any]:
        value = inputs.get(key)
        if value is None:
            return {}
        if not isinstance(value, dict):
            raise ModuleValidationError(f"inputs.{key} must be a mapping when set")
        return value

    location = req_str("location")
    if len(location) > 64:
        raise ModuleValidationError("inputs.location looks invalid")

    name_prefix = opt_str("name_prefix")
    context_id = opt_str("context_id")
    if name_prefix and not _SLUG_RE.fullmatch(name_prefix):
        raise ModuleValidationError("inputs.name_prefix must match [a-z0-9-] and start/end alnum")
    if context_id and not _SLUG_RE.fullmatch(context_id):
        raise ModuleValidationError("inputs.context_id must match [a-z0-9-] and start/end alnum")

    resource_group_name = opt_str("resource_group_name")
    if resource_group_name and len(resource_group_name) > 90:
        raise ModuleValidationError("inputs.resource_group_name must be 90 characters or fewer")

    storage_account_name = opt_str("storage_account_name")
    if storage_account_name and not _STORAGE_ACCOUNT_RE.fullmatch(storage_account_name):
        raise ModuleValidationError("inputs.storage_account_name must match ^[a-z0-9]{3,24}$")

    container_name = req_str("container_name").lower()
    if not _CONTAINER_RE.fullmatch(container_name):
        raise ModuleValidationError(
            "inputs.container_name must match ^[a-z0-9](?:[a-z0-9-]{1,61}[a-z0-9])?$"
        )
    if "--" in container_name:
        raise ModuleValidationError("inputs.container_name must not contain consecutive hyphens")

    account_tier = req_str("account_tier")
    if account_tier not in {"Standard", "Premium"}:
        raise ModuleValidationError("inputs.account_tier must be one of: Standard, Premium")

    replication = req_str("account_replication_type")
    if replication not in {"LRS", "GRS", "RAGRS", "ZRS", "GZRS", "RAGZRS"}:
        raise ModuleValidationError(
            "inputs.account_replication_type must be one of: LRS, GRS, RAGRS, ZRS, GZRS, RAGZRS"
        )

    access_tier = req_str("access_tier")
    if access_tier not in {"Hot", "Cool"}:
        raise ModuleValidationError("inputs.access_tier must be one of: Hot, Cool")

    min_tls = req_str("min_tls_version")
    if min_tls not in {"TLS1_0", "TLS1_1", "TLS1_2"}:
        raise ModuleValidationError("inputs.min_tls_version must be one of: TLS1_0, TLS1_1, TLS1_2")

    opt_bool("versioning_enabled")
    opt_bool("shared_access_key_enabled")
    opt_bool("public_network_access_enabled")

    lifecycle_days = opt_num("lifecycle_delete_age_days")
    if lifecycle_days < 0:
        raise ModuleValidationError("inputs.lifecycle_delete_age_days must be >= 0")

    tags = opt_dict("tags")
    for key, value in tags.items():
        if not isinstance(key, str) or not key.strip():
            raise ModuleValidationError("inputs.tags keys must be non-empty strings")
        if not isinstance(value, str):
            raise ModuleValidationError("inputs.tags values must be strings")
