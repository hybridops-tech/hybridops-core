"""Common validator primitives.

purpose: Shared low-level validation helpers used by module validators.
Architecture Decision: ADR-N/A (validator helper consolidation)
maintainer: HybridOps.Tech
"""

from __future__ import annotations

from typing import Any

from hyops.validators.registry import ModuleValidationError


_VALID_LIFECYCLE_COMMANDS = {"apply", "deploy", "destroy", "import", "plan", "validate"}

# Placeholder tokens that should never appear in real input values.
_PLACEHOLDER_MARKERS = ("CHANGE_ME", "REPLACE_ME", "YOUR_VALUE")


def check_no_placeholder(value: str, field: str) -> str:
    """Raise if *value* looks like an unfilled template placeholder."""
    normalised = value.upper().replace("-", "_")
    if any(normalised.startswith(m) or ("_" + m + "_") in normalised for m in _PLACEHOLDER_MARKERS):
        raise ModuleValidationError(f"{field} must not contain placeholder values (found {value!r})")
    return value


def require_mapping(value: Any, field: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ModuleValidationError(f"{field} must be a mapping")
    return value


def require_non_empty_str(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ModuleValidationError(f"{field} must be a non-empty string")
    return value.strip()


def require_bool(value: Any, field: str) -> bool:
    if not isinstance(value, bool):
        raise ModuleValidationError(f"{field} must be a boolean")
    return value


def require_port(value: Any, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ModuleValidationError(f"{field} must be an integer")
    if value < 1 or value > 65535:
        raise ModuleValidationError(f"{field} must be between 1 and 65535")
    return value


def require_int_ge(value: Any, field: str, minimum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ModuleValidationError(f"{field} must be an integer")
    if value < minimum:
        raise ModuleValidationError(f"{field} must be >= {minimum}")
    return value


def require_positive_int(value: Any, field: str) -> int:
    return require_int_ge(value, field, 1)


def require_number_ge(value: Any, field: str, minimum: float) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ModuleValidationError(f"{field} must be a number")
    token = float(value)
    if token < minimum:
        raise ModuleValidationError(f"{field} must be >= {minimum}")
    return token


def require_str_list(value: Any, field: str) -> list[str]:
    if not isinstance(value, list):
        raise ModuleValidationError(f"{field} must be a list")
    return [require_non_empty_str(item, f"{field}[{idx}]") for idx, item in enumerate(value, start=1)]


def normalize_required_env(value: Any, field: str) -> list[str]:
    if value is None:
        return []
    return require_str_list(value, field)


# ── Optional-field helpers ────────────────────────────────────────────────────
# Use these shared primitives directly, or via thin local adapters when a
# validator wants to keep `(inputs, key)` call sites. Do not redefine the
# low-level type/placeholder helpers in individual validators.

def opt_str(value: Any, field: str, *, default: str = "") -> str:
    """Return stripped string value, or *default* if absent/None."""
    if value is None:
        return default
    if not isinstance(value, str):
        raise ModuleValidationError(f"{field} must be a string when set")
    return value.strip()


def opt_bool(value: Any, field: str, *, default: bool | None = None) -> bool | None:
    """Return bool value, or *default* if absent/None."""
    if value is None:
        return default
    if not isinstance(value, bool):
        raise ModuleValidationError(f"{field} must be a boolean when set")
    return value


def opt_int(value: Any, field: str, *, minimum: int | None = None) -> int | None:
    """Return int value, or None if absent.  Rejects booleans masquerading as ints."""
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        raise ModuleValidationError(f"{field} must be an integer when set")
    if minimum is not None and value < minimum:
        raise ModuleValidationError(f"{field} must be >= {minimum} when set")
    return value


def opt_str_list(value: Any, field: str) -> list[str]:
    """Return list of non-empty strings, or [] if absent/None."""
    if value is None:
        return []
    return require_str_list(value, field)


def opt_mapping(value: Any, field: str) -> dict[str, Any]:
    """Return dict, or {} if absent/None."""
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ModuleValidationError(f"{field} must be a mapping when set")
    return value


def normalize_lifecycle_command(
    inputs: Any,
    *,
    field: str = "_hyops_lifecycle_command",
    legacy_fields: tuple[str, ...] = ("hyops_lifecycle_command",),
    allow_empty: bool = True,
) -> str:
    data = require_mapping(inputs, "inputs")

    resolved_fields: dict[str, str] = {}
    for candidate in (field, *legacy_fields):
        raw = data.get(candidate)
        if raw is None:
            continue
        if not isinstance(raw, str):
            raise ModuleValidationError(f"inputs.{candidate} must be a string when set")
        token = raw.strip().lower()
        if not token:
            continue
        resolved_fields[candidate] = token

    if not resolved_fields:
        if allow_empty:
            return ""
        raise ModuleValidationError(f"inputs.{field} is required")

    commands = set(resolved_fields.values())
    if len(commands) != 1:
        details = ", ".join(
            f"inputs.{candidate}={value}" for candidate, value in sorted(resolved_fields.items())
        )
        raise ModuleValidationError(f"lifecycle command inputs disagree: {details}")

    lifecycle = next(iter(commands))
    if lifecycle not in _VALID_LIFECYCLE_COMMANDS:
        allowed = ", ".join(sorted(_VALID_LIFECYCLE_COMMANDS))
        raise ModuleValidationError(f"lifecycle command must be one of: {allowed}")
    return lifecycle
