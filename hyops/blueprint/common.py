"""Common helper utilities for blueprint command modules."""

from __future__ import annotations

from typing import Any


def as_mapping(value: Any, field: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"{field} must be a mapping")
    return value


def as_non_empty_string(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be a non-empty string")
    return value.strip()


def bool_field(value: Any, field: str) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    raise ValueError(f"{field} must be a boolean when set")


def merge_mappings(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = merge_mappings(dict(out[key]), value)
            continue
        out[key] = value
    return out

