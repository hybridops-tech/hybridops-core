"""
purpose: Driver registry and loading for HybridOps.Core.
maintainer: HybridOps.Tech
"""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any, Callable, Iterator


DriverFunc = Callable[[dict[str, Any]], dict[str, Any]]
ExecutionValidator = Callable[[dict[str, Any]], None]


@dataclass(frozen=True)
class DriverRegistration:
    ref: str
    source: str  # "builtin" | "plugin:<name>" | "internal"
    fn: DriverFunc
    execution_validator: ExecutionValidator | None = None


class DriverUnavailableError(LookupError):
    """Selected driver is unavailable after plugin discovery failed."""

    def __init__(self, ref: str, failed_plugins: tuple[str, ...]) -> None:
        self.ref = ref
        self.failed_plugins = failed_plugins
        names = ", ".join(failed_plugins)
        super().__init__(
            f"driver unavailable: {ref} (plugin registration failed: {names})"
        )


class DriverRegistry:
    def __init__(self) -> None:
        self._drivers: dict[str, DriverRegistration] = {}
        self._reserved: set[str] = set()
        self._failed_plugins: set[str] = set()

    @contextmanager
    def plugin_registration(self, entrypoint: str) -> Iterator[None]:
        """Roll back registrations when one plugin cannot load completely."""
        name = str(entrypoint or "").strip() or "unknown"
        drivers_before = dict(self._drivers)
        reserved_before = set(self._reserved)
        try:
            yield
        except Exception:
            self._drivers = drivers_before
            self._reserved = reserved_before
            self._failed_plugins.add(name)
            raise
        else:
            self._failed_plugins.discard(name)

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
        reg = self._require_registration(ref)
        return reg.fn

    def validate_execution(self, ref: str, execution: dict[str, Any]) -> None:
        reg = self._require_registration(ref)

        if reg.execution_validator is None:
            return

        if not isinstance(execution, dict):
            raise ValueError("execution spec must be a mapping")

        reg.execution_validator(execution)

    def list(self) -> list[DriverRegistration]:
        return sorted(self._drivers.values(), key=lambda r: r.ref)

    def _require_registration(self, ref: str) -> DriverRegistration:
        reg = self._drivers.get(ref)
        if reg is not None:
            return reg
        if self._failed_plugins:
            raise DriverUnavailableError(ref, tuple(sorted(self._failed_plugins)))
        raise KeyError(f"driver not registered: {ref}")

    @staticmethod
    def _validate_ref(ref: str) -> None:
        if not ref or "/" not in ref:
            raise ValueError(f"invalid driver ref: {ref}")


REGISTRY = DriverRegistry()
