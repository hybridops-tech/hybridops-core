"""
purpose: Driver registry and loading for HybridOps.Core.
maintainer: HybridOps.Tech
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable


DriverFunc = Callable[[dict[str, Any]], dict[str, Any]]
ExecutionValidator = Callable[[dict[str, Any]], None]
ControllerCheck = Callable[[dict[str, Any]], str]
StateInspector = Callable[[dict[str, Any]], tuple[str, str]]


@dataclass(frozen=True)
class DriverRegistration:
    ref: str
    source: str  # "builtin" | "plugin:<name>" | "internal"
    fn: DriverFunc
    execution_validator: ExecutionValidator | None = None
    controller_check: ControllerCheck | None = None
    state_inspector: StateInspector | None = None


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
        controller_check: ControllerCheck | None = None,
        state_inspector: StateInspector | None = None,
    ) -> None:
        self._validate_ref(ref)

        if not callable(fn):
            raise TypeError(f"driver is not callable: {ref}")
        for capability_name, capability in (
            ("execution validator", execution_validator),
            ("controller check", controller_check),
            ("state inspector", state_inspector),
        ):
            if capability is not None and not callable(capability):
                raise TypeError(f"driver {capability_name} is not callable: {ref}")

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
            controller_check=controller_check,
            state_inspector=state_inspector,
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

    def check_controller(self, ref: str, request: dict[str, Any]) -> str:
        reg = self._registration(ref)
        if reg.controller_check is None:
            return ""
        result = reg.controller_check(request)
        if not isinstance(result, str):
            raise TypeError(f"driver controller check returned invalid result: {ref}")
        return result.strip()

    def inspect_state(self, ref: str, request: dict[str, Any]) -> tuple[str, str]:
        reg = self._registration(ref)
        if reg.state_inspector is None:
            return "safe", ""
        result = reg.state_inspector(request)
        if not isinstance(result, tuple) or len(result) != 2:
            raise TypeError(f"driver state inspector returned invalid result: {ref}")
        status = str(result[0] or "").strip().lower()
        detail = str(result[1] or "").strip()
        if status not in {"safe", "stale", "error"}:
            raise ValueError(
                f"driver state inspector returned invalid status: {ref} ({status or '<empty>'})"
            )
        return status, detail

    def list(self) -> list[DriverRegistration]:
        return sorted(self._drivers.values(), key=lambda r: r.ref)

    def _registration(self, ref: str) -> DriverRegistration:
        reg = self._drivers.get(ref)
        if not reg:
            raise KeyError(f"driver not registered: {ref}")
        return reg

    @staticmethod
    def _validate_ref(ref: str) -> None:
        if not ref or "/" not in ref:
            raise ValueError(f"invalid driver ref: {ref}")


REGISTRY = DriverRegistry()
