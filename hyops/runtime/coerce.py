"""hyops.runtime.coerce

purpose: Small, consistent coercion helpers used across drivers/commands.
Architecture Decision: ADR-N/A
maintainer: HybridOps.Tech
"""

from __future__ import annotations

from typing import Any


def as_bool(value: Any, *, default: bool = False) -> bool:
    """Best-effort boolean coercion.

    Keeps semantics intentionally forgiving for CLI/env/profile inputs.
    """

    if isinstance(value, bool):
        return value
    if value is None:
        return default
    if isinstance(value, (int, float)):
        return value != 0
    if isinstance(value, str):
        token = value.strip().lower()
        if token in ("1", "true", "yes", "on"):
            return True
        if token in ("0", "false", "no", "off", ""):
            return False
    return default


def as_int(value: Any, *, default: int = 0) -> int:
    """Best-effort int coercion.

    Note: string parsing uses int(token) and may raise ValueError.
    Callers that accept operator input should wrap in try/except.
    """

    if value is None:
        return default
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str):
        token = value.strip()
        if not token:
            return default
        return int(token)
    return default


def as_argv(value: Any, default: list[str]) -> list[str]:
    """Coerce a YAML/JSON list into an argv list.

    Drops empty/whitespace entries.
    """

    if not isinstance(value, list) or not value:
        return list(default)

    out: list[str] = []
    for item in value:
        token = str(item or "").strip()
        if token:
            out.append(token)

    return out or list(default)


def as_positive_int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value if value > 0 else None
    if isinstance(value, str):
        token = value.strip()
        if not token:
            return None
        try:
            parsed = int(token)
        except Exception:
            return None
        return parsed if parsed > 0 else None
    return None


def as_non_negative_int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value if value >= 0 else None
    if isinstance(value, str):
        token = value.strip()
        if not token:
            return None
        try:
            parsed = int(token)
        except Exception:
            return None
        return parsed if parsed >= 0 else None
    return None


def as_port(value: Any) -> int | None:
    parsed = as_positive_int(value)
    if parsed is None:
        return None
    if parsed < 1 or parsed > 65535:
        return None
    return parsed

