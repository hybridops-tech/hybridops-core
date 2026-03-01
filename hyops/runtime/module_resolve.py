"""
purpose: Resolve module spec and operator-provided inputs into a single request payload.
Architecture Decision: ADR-N/A (module resolution)
maintainer: HybridOps.Studio
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any
import yaml

from hyops.runtime.addressing_contract import validate_addressing_contract
from hyops.runtime.module_dependencies import (
    resolve_dependencies as _resolve_dependencies,
    resolve_execution_hooks as _resolve_execution_hooks,
    resolve_outputs_publish as _resolve_outputs_publish,
    resolve_required_credentials as _resolve_required_credentials,
)
from hyops.runtime.module_inputs import apply_env_overrides as _apply_env_overrides
from hyops.runtime.module_state_contracts import (
    resolve_cloudsql_target_contract_from_state as _resolve_cloudsql_target_contract_from_state,
    resolve_db_contract_from_state as _resolve_db_contract_from_state,
    resolve_inventory_groups_from_state as _resolve_inventory_groups_from_state,
    resolve_network_contract_from_state as _resolve_network_contract_from_state,
    resolve_prefixed_db_contract_from_state as _resolve_prefixed_db_contract_from_state,
    resolve_prefixed_repo_contract_from_state as _resolve_prefixed_repo_contract_from_state,
    resolve_postgresql_dr_source_contract_from_state as _resolve_postgresql_dr_source_contract_from_state,
    resolve_project_contract_from_state as _resolve_project_contract_from_state,
    resolve_repo_contract_from_state as _resolve_repo_contract_from_state,
    resolve_router_contract_from_state as _resolve_router_contract_from_state,
    resolve_ssh_keys_from_init as _resolve_ssh_keys_from_init,
    resolve_target_host_from_state as _resolve_target_host_from_state,
)
from hyops.runtime.presets import resolve_preset_overlay
from hyops.runtime.refs import normalize_module_ref
from hyops.validators.registry import ModuleValidationError, validate_module_inputs


@dataclass(frozen=True)
class ModuleResolved:
    module_ref: str
    module_dir: Path
    spec: dict[str, Any]
    inputs: dict[str, Any]
    execution: dict[str, Any]
    required_credentials: list[str]
    dependencies: list[dict[str, Any]]
    dependency_warnings: list[str]
    outputs_publish: list[str]


def _load_yaml(path: Path) -> dict[str, Any]:
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        raise ValueError(f"invalid YAML object: {path}")
    return data


def resolve_module(
    module_ref: str,
    module_root: Path,
    inputs_file: Path | None,
    state_dir: Path | None = None,
    lifecycle_command: str | None = None,
    assumed_state_ok: set[str] | None = None,
) -> ModuleResolved:
    module_ref = normalize_module_ref(module_ref)
    if not module_ref:
        raise ValueError("module_ref is required")

    module_dir = (module_root / module_ref).resolve()
    spec_path = module_dir / "spec.yml"
    if not spec_path.exists():
        raise FileNotFoundError(f"spec not found: {spec_path}")

    spec = _load_yaml(spec_path)

    spec_module_ref = normalize_module_ref(str(spec.get("module_ref") or "").strip())
    if spec_module_ref and spec_module_ref != module_ref:
        raise ValueError(
            f"spec.module_ref mismatch: expected {module_ref}, found {spec_module_ref}"
        )

    raw_exec = spec.get("execution") or {}
    if not isinstance(raw_exec, dict):
        raise ValueError("spec.execution must be a mapping")

    driver = str(raw_exec.get("driver") or "").strip()
    profile = str(raw_exec.get("profile") or "").strip()

    pack_ref = raw_exec.get("pack_ref") or {}
    if not isinstance(pack_ref, dict):
        raise ValueError("spec.execution.pack_ref must be a mapping")

    pack_id = str(pack_ref.get("id") or "").strip()

    if not driver or not profile or not pack_id:
        raise ValueError("spec.execution requires driver, profile, and pack_ref.id")

    execution = {
        "driver": driver,
        "profile": profile,
        "pack_id": pack_id,
        "hooks": _resolve_execution_hooks(raw_exec),
    }

    required_credentials = _resolve_required_credentials(spec, module_ref, pack_id)
    outputs_publish = _resolve_outputs_publish(spec)

    spec_inputs = spec.get("inputs") or {}
    if spec_inputs and not isinstance(spec_inputs, dict):
        raise ValueError("spec.inputs must be a mapping")

    defaults = spec_inputs.get("defaults") or {}
    if defaults and not isinstance(defaults, dict):
        raise ValueError("spec.inputs.defaults must be a mapping")

    operator_inputs: dict[str, Any] = {}
    if inputs_file:
        op = _load_yaml(inputs_file)
        if not isinstance(op, dict):
            raise ValueError("inputs file must be a mapping")
        operator_inputs = op

    inputs = resolve_preset_overlay(
        module_ref=module_ref,
        defaults=defaults,
        spec_inputs=spec_inputs,
        operator_inputs=operator_inputs,
    )

    state_root = Path(state_dir).expanduser().resolve() if state_dir else None
    dependency_inputs, dependencies, dependency_warnings = _resolve_dependencies(
        spec,
        module_ref,
        state_root,
        assumed_state_ok=assumed_state_ok,
    )
    if dependency_inputs:
        inputs.update(dependency_inputs)

    if operator_inputs:
        inputs.update(operator_inputs)

    inputs = _apply_env_overrides(inputs)
    _resolve_target_host_from_state(inputs, state_root=state_root, assumed_state_ok=assumed_state_ok)
    _resolve_inventory_groups_from_state(inputs, state_root=state_root, assumed_state_ok=assumed_state_ok)
    _resolve_db_contract_from_state(inputs, state_root=state_root, assumed_state_ok=assumed_state_ok)
    _resolve_prefixed_db_contract_from_state(inputs, prefix="source", state_root=state_root, assumed_state_ok=assumed_state_ok)
    _resolve_prefixed_db_contract_from_state(inputs, prefix="target", state_root=state_root, assumed_state_ok=assumed_state_ok)
    _resolve_network_contract_from_state(inputs, state_root=state_root, assumed_state_ok=assumed_state_ok)
    _resolve_project_contract_from_state(inputs, state_root=state_root, assumed_state_ok=assumed_state_ok)
    _resolve_router_contract_from_state(inputs, state_root=state_root, assumed_state_ok=assumed_state_ok)
    _resolve_repo_contract_from_state(inputs, state_root=state_root, assumed_state_ok=assumed_state_ok)
    _resolve_postgresql_dr_source_contract_from_state(
        inputs, state_root=state_root, assumed_state_ok=assumed_state_ok
    )
    _resolve_cloudsql_target_contract_from_state(
        inputs, state_root=state_root, assumed_state_ok=assumed_state_ok
    )
    _resolve_prefixed_repo_contract_from_state(
        inputs, prefix="secondary", state_root=state_root, assumed_state_ok=assumed_state_ok
    )
    validate_addressing_contract(inputs)

    # Validators sometimes need lifecycle context (e.g., destroy should validate a
    # smaller input surface). Do NOT leak internal context keys into driver inputs,
    # because some drivers forward all inputs to downstream tools (e.g., Terraform
    # variables) which would break on unknown keys.
    inputs_for_validation = dict(inputs)
    if lifecycle_command is not None:
        token = str(lifecycle_command or "").strip().lower()
        if token:
            inputs_for_validation["_hyops_lifecycle_command"] = token

    try:
        validate_module_inputs(module_ref, inputs_for_validation)
    except ModuleValidationError as e:
        raise ValueError(f"input validation failed for {module_ref}: {e}") from e

    _resolve_ssh_keys_from_init(inputs, state_root=state_root)

    return ModuleResolved(
        module_ref=module_ref,
        module_dir=module_dir,
        spec=spec,
        inputs=inputs,
        execution=execution,
        required_credentials=required_credentials,
        dependencies=dependencies,
        dependency_warnings=dependency_warnings,
        outputs_publish=outputs_publish,
    )
