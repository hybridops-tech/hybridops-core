"""
purpose: Validate config/ansible execution schema before driver invocation.
Architecture Decision: ADR-N/A (config ansible execution schema)
maintainer: HybridOps.Studio
"""

from __future__ import annotations

from typing import Any


_ALLOWED_EXEC_KEYS = {"driver", "profile", "pack_ref"}
_ALLOWED_PACK_REF_KEYS = {"id"}


def _require_mapping(value: Any, *, field: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"{field} must be a mapping")
    return value


def _reject_unknown_keys(payload: dict[str, Any], *, field: str, allowed: set[str]) -> None:
    unknown = sorted([str(k) for k in payload.keys() if str(k) not in allowed])
    if unknown:
        raise ValueError(f"{field} has unknown keys: {', '.join(unknown)}")


def validate_execution_schema(raw_exec: dict[str, Any]) -> None:
    exec_map = _require_mapping(raw_exec, field="spec.execution")
    _reject_unknown_keys(exec_map, field="spec.execution", allowed=_ALLOWED_EXEC_KEYS)

    if "pack_ref" in exec_map:
        pack_ref = _require_mapping(exec_map.get("pack_ref"), field="spec.execution.pack_ref")
        _reject_unknown_keys(pack_ref, field="spec.execution.pack_ref", allowed=_ALLOWED_PACK_REF_KEYS)
