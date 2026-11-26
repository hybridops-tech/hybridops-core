"""Resolve module driver capabilities."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from hyops.drivers import registry as driver_registry
from hyops.drivers.registry import DriverRegistry
from hyops.runtime.module_resolve import resolve_module_execution


def module_driver_ref(module_ref: str, module_root: Path) -> str:
    execution = resolve_module_execution(module_ref, module_root)
    return str(execution["driver"])


def check_driver_controller(
    *,
    driver_ref: str,
    request: dict[str, Any],
    registry: DriverRegistry | None = None,
) -> str:
    active_registry = registry if registry is not None else driver_registry.REGISTRY
    return active_registry.check_controller(driver_ref, request)


def inspect_module_state(
    *,
    module_ref: str,
    module_root: Path,
    request: dict[str, Any],
    registry: DriverRegistry | None = None,
) -> tuple[str, str]:
    driver_ref = module_driver_ref(module_ref, module_root)
    active_registry = registry if registry is not None else driver_registry.REGISTRY
    return active_registry.inspect_state(driver_ref, request)
