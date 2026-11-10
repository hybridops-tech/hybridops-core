"""
purpose: Module input validation registry and built-in validators.
Architecture Decision: ADR-0206 (module execution contract v1)
maintainer: HybridOps.Tech
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable
import yaml


class ModuleValidationError(ValueError):
    pass


ValidatorFn = Callable[[dict[str, Any]], None]


@dataclass(frozen=True)
class ValidatorEntry:
    module_ref: str
    validate: ValidatorFn


_REGISTRY: dict[str, ValidatorFn] = {}
_PRODUCTION_MODULES: set[str] | None = None


def _get_production_modules() -> set[str]:
    """Dynamically load production modules from registry at runtime."""
    global _PRODUCTION_MODULES
    if _PRODUCTION_MODULES is not None:
        return _PRODUCTION_MODULES

    _PRODUCTION_MODULES = set(_REGISTRY.keys())
    return _PRODUCTION_MODULES


def register(module_ref: str, fn: ValidatorFn) -> None:
    m = (module_ref or "").strip()
    if not m:
        raise ModuleValidationError("module_ref is required")
    if not callable(fn):
        raise ModuleValidationError("validator must be callable")
    if m in _REGISTRY:
        raise ModuleValidationError(f"validator already registered for module_ref={m}")
    _REGISTRY[m] = fn
    # Invalidate cache when new validator registered
    global _PRODUCTION_MODULES
    _PRODUCTION_MODULES = None


def validate_module_inputs(
    module_ref: str,
    inputs: dict[str, Any],
    require_validator: bool = True,
    lifecycle_command: str | None = None
) -> None:
    """Validate module inputs with runtime enforcement.

    Args:
        module_ref: Module reference (e.g., "platform/linux/containerlab")
        inputs: Input dictionary to validate
        require_validator: Enforce validation (default True for production)
        lifecycle_command: Lifecycle command (validate/plan/preflight/apply)

    Raises:
        ModuleValidationError: If validation fails or validator not found
    """
    m = (module_ref or "").strip()
    fn = _REGISTRY.get(m)

    if not fn:
        if require_validator:
            raise ModuleValidationError(
                f"input validation required but no validator registered for {m}. "
                "All production modules must have enforced input contracts."
            )
        return

    if not isinstance(inputs, dict):
        raise ModuleValidationError("inputs must be a mapping")

    # Validate API version and kind if present
    if "api_version" in inputs and inputs["api_version"] not in {"hybridops/v1"}:
        raise ModuleValidationError(
            f"unsupported api_version: {inputs.get('api_version')}. "
            "Must be hybridops/v1"
        )

    if "kind" in inputs and inputs["kind"] not in {"ModuleSpec", "BlueprintSpec"}:
        raise ModuleValidationError(
            f"unsupported kind: {inputs.get('kind')}. "
            "Must be ModuleSpec or BlueprintSpec"
        )

    # Enforce lifecycle-path consistency
    if lifecycle_command:
        valid_commands = {"validate", "plan", "preflight", "apply", "destroy", "output"}
        if lifecycle_command not in valid_commands:
            raise ModuleValidationError(
                f"invalid lifecycle_command: {lifecycle_command}. "
                f"Must be one of {valid_commands}"
            )

    try:
        fn(inputs)
    except ModuleValidationError:
        raise
    except Exception as e:
        raise ModuleValidationError(f"validator failed for module_ref={m}: {e}") from e