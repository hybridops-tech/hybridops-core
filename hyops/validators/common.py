"""Common validator primitives.

purpose: Shared low-level validation helpers used by module validators.
Architecture Decision: ADR-N/A (validator helper consolidation)
maintainer: HybridOps.Studio
"""

from __future__ import annotations

from typing import Any


def require_mapping(value: Any, field: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"{field} must be a mapping")
    return value


def require_non_empty_str(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be a non-empty string")
    return value.strip()


def require_port(value: Any, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{field} must be an integer")
    if value < 1 or value > 65535:
        raise ValueError(f"{field} must be between 1 and 65535")
    return value


def normalize_required_env(value: Any, field: str) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise ValueError(f"{field} must be a list when set")
    out: list[str] = []
    for idx, item in enumerate(value, start=1):
        out.append(require_non_empty_str(item, f"{field}[{idx}]"))
    return out
