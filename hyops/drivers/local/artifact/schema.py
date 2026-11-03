"""Validate the local artifact execution contract."""

from __future__ import annotations

from typing import Any


_ALLOWED_EXEC_KEYS = {"driver", "profile", "pack_ref"}
_ALLOWED_PACK_REF_KEYS = {"id"}


def validate_execution_schema(raw_exec: dict[str, Any]) -> None:
    if not isinstance(raw_exec, dict):
        raise ValueError("spec.execution must be a mapping")

    unknown = sorted(str(key) for key in raw_exec if str(key) not in _ALLOWED_EXEC_KEYS)
    if unknown:
        raise ValueError(f"spec.execution has unknown keys: {', '.join(unknown)}")

    pack_ref = raw_exec.get("pack_ref")
    if not isinstance(pack_ref, dict):
        raise ValueError("spec.execution.pack_ref must be a mapping")
    unknown_pack_keys = sorted(
        str(key) for key in pack_ref if str(key) not in _ALLOWED_PACK_REF_KEYS
    )
    if unknown_pack_keys:
        raise ValueError(
            "spec.execution.pack_ref has unknown keys: "
            + ", ".join(unknown_pack_keys)
        )
