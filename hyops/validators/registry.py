"""
purpose: Module input validation registry and built-in validators.
Architecture Decision: ADR-0206 (module execution contract v1)
maintainer: HybridOps.Studio
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable


class ModuleValidationError(ValueError):
    pass


ValidatorFn = Callable[[dict[str, Any]], None]


@dataclass(frozen=True)
class ValidatorEntry:
    module_ref: str
    validate: ValidatorFn


_REGISTRY: dict[str, ValidatorFn] = {}


def register(module_ref: str, fn: ValidatorFn) -> None:
    m = (module_ref or "").strip()
    if not m:
        raise ModuleValidationError("module_ref is required")
    if not callable(fn):
        raise ModuleValidationError("validator must be callable")
    if m in _REGISTRY:
        raise ModuleValidationError(f"validator already registered for module_ref={m}")
    _REGISTRY[m] = fn


def validate_module_inputs(module_ref: str, inputs: dict[str, Any]) -> None:
    m = (module_ref or "").strip()
    fn = _REGISTRY.get(m)
    if not fn:
        return

    if not isinstance(inputs, dict):
        raise ModuleValidationError("inputs must be a mapping")

    try:
        fn(inputs)
    except ModuleValidationError:
        raise
    except Exception as e:
        raise ModuleValidationError(f"validator failed for module_ref={m}: {e}") from e