"""Terragrunt execution driver."""

from __future__ import annotations

from typing import Any

from .contracts import get_contract
from .driver import run
from .schema import validate_execution_schema


def inspect_state(request: dict[str, Any]) -> tuple[str, str]:
    module_ref = str(request.get("module_ref") or "").strip()
    contract = get_contract(module_ref)
    return contract.evaluate_state_skip(
        command_name=str(request.get("command_name") or "").strip(),
        module_ref=module_ref,
        state_root=request["state_root"],
        state_instance=request.get("state_instance"),
        credentials_dir=request["credentials_dir"],
        runtime_root=request["runtime_root"],
        env={str(key): str(value) for key, value in request.get("env", {}).items()},
    )


__all__ = ["inspect_state", "run", "validate_execution_schema"]
