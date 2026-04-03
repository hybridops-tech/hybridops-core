"""
purpose: Driver registry and loading for HybridOps.Core.
maintainer: HybridOps.Tech
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable


DriverFunc = Callable[[dict[str, Any]], dict[str, Any]]
ExecutionValidator = Callable[[dict[str, Any]], None]


@dataclass(frozen=True)
class DriverRegistration:
    ref: str
    source: str  # "builtin" | "plugin:<name>" | "internal"
    fn: DriverFunc
    execution_validator: ExecutionValidator | None = None


class DriverRegistry:
    def __init__(self) -> None:
        self._drivers: dict[str, DriverRegistration] = {}
        self._reserved: set[str] = set()

    def reserve(self, ref: str) -> None:
        self._validate_ref(ref)
        self._reserved.add(ref)

    def register(
        self,
        ref: str,
        fn: DriverFunc,
        *,
        source: str = "internal",
        allow_override: bool = False,
        execution_validator: ExecutionValidator | None = None,
    ) -> None:
        self._validate_ref(ref)

        if not callable(fn):
            raise TypeError(f"driver is not callable: {ref}")

        if ref in self._reserved and not allow_override:
            # Reserved means “plugins cannot replace this”.
            existing = self._drivers.get(ref)
            if existing is not None:
                raise ValueError(
                    f"driver ref is reserved and already registered: {ref} (existing_source={existing.source})"
                )
            # reserved but not registered yet: still allow first registration by internal/builtin path
            if source.startswith("plugin:"):
                raise ValueError(f"driver ref is reserved and cannot be registered by plugin: {ref}")

        existing = self._drivers.get(ref)
        if existing is not None and not allow_override:
            raise ValueError(f"driver already registered: {ref} (existing_source={existing.source})")

        self._drivers[ref] = DriverRegistration(
            ref=ref,
            source=source,
            fn=fn,
            execution_validator=execution_validator,
        )

    def resolve(self, ref: str) -> DriverFunc:
        reg = self._drivers.get(ref)
        if not reg:
            raise KeyError(f"driver not registered: {ref}")
        return reg.fn

    def validate_execution(self, ref: str, execution: dict[str, Any]) -> None:
        reg = self._drivers.get(ref)
        if not reg:
            raise KeyError(f"driver not registered: {ref}")

        if reg.execution_validator is None:
            return

        if not isinstance(execution, dict):
            raise ValueError("execution spec must be a mapping")

        reg.execution_validator(execution)

    def list(self) -> list[DriverRegistration]:
        return sorted(self._drivers.values(), key=lambda r: r.ref)

    @staticmethod
    def _validate_ref(ref: str) -> None:
        if not ref or "/" not in ref:
            raise ValueError(f"invalid driver ref: {ref}")


REGISTRY = DriverRegistry()