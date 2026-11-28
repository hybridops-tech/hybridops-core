"""Continuity contract validation and deterministic ordering."""

from __future__ import annotations

import heapq
import math
import re
from collections.abc import Mapping
from types import MappingProxyType

from hyops.authority.models import AuthorityDeclaration, AuthorityRequirement

from .adapter import ContinuityAdapter
from .errors import ContractFailure
from .models import (
    ADAPTER_CONTRACT_VERSION,
    CONTINUITY_CONTRACT_SCHEMA_VERSION,
    CONTINUITY_KIND,
    AdapterIdentity,
    ContinuityContract,
    EvidenceBinding,
    InputBinding,
    StageSpec,
    WorkloadIdentity,
)

_TOKEN_RE = re.compile(r"^[a-z][a-z0-9_-]{0,63}$")
_SHA256_RE = re.compile(r"^sha256:[0-9a-f]{64}$")

_AdapterContract = tuple[AdapterIdentity, tuple[str, ...]]


def is_token(value: object) -> bool:
    return isinstance(value, str) and _TOKEN_RE.fullmatch(value) is not None


def is_sha256_digest(value: object) -> bool:
    return isinstance(value, str) and _SHA256_RE.fullmatch(value) is not None


def validate_contract_semantics(
    contract: ContinuityContract,
    adapters: Mapping[str, ContinuityAdapter],
) -> tuple[tuple[str, ...], Mapping[str, _AdapterContract]]:
    if contract.schema_version != CONTINUITY_CONTRACT_SCHEMA_VERSION:
        raise ContractFailure(
            "unsupported_contract_version",
            "unsupported continuity contract schema version "
            f"'{contract.schema_version}'",
        )
    if contract.kind != CONTINUITY_KIND:
        raise ContractFailure(
            "invalid_contract_kind",
            f"unsupported continuity contract kind '{contract.kind}'",
        )
    if not contract.stages:
        raise ContractFailure("empty_contract", "continuity contract has no stages")

    by_id: dict[str, StageSpec] = {}
    adapter_contracts: dict[str, _AdapterContract] = {}
    for stage in contract.stages:
        if stage.id in by_id:
            raise ContractFailure(
                "duplicate_stage",
                f"duplicate continuity stage: {stage.id}",
            )
        by_id[stage.id] = stage
        if stage.adapter not in adapter_contracts:
            adapter_contracts[stage.adapter] = _validate_adapter_contract(
                stage.adapter,
                adapters,
            )
        _validate_stage_adapter(stage, adapter_contracts[stage.adapter])
        if set(stage.inputs) & set(stage.input_bindings):
            raise ContractFailure(
                "duplicate_input",
                f"stage '{stage.id}' declares an input as both literal and binding",
            )
        if len(stage.evidence_bindings) != len(set(stage.evidence_bindings)):
            raise ContractFailure(
                "duplicate_evidence_binding",
                f"stage '{stage.id}' declares a duplicate evidence binding",
            )
        if stage.authority is not None:
            _validate_authority_binding(contract, stage)

    for stage in contract.stages:
        if len(stage.requires) != len(set(stage.requires)):
            raise ContractFailure(
                "duplicate_dependency",
                f"stage '{stage.id}' declares a duplicate dependency",
            )
        for dependency in stage.requires:
            if dependency not in by_id:
                raise ContractFailure(
                    "unknown_dependency",
                    f"stage '{stage.id}' requires unknown stage '{dependency}'",
                )
            if dependency == stage.id:
                raise ContractFailure(
                    "dependency_cycle",
                    f"stage '{stage.id}' cannot require itself",
                )
        reachable = _dependencies(stage.id, by_id)
        for name, binding in stage.input_bindings.items():
            _validate_binding(stage, name, binding, by_id, reachable)
        for binding in stage.evidence_bindings:
            _validate_evidence_binding(stage, binding, by_id, reachable)

    return _topological_order(by_id), MappingProxyType(adapter_contracts)


def validate_contract_shape(contract: ContinuityContract) -> None:
    if not isinstance(contract, ContinuityContract):
        raise ContractFailure(
            "invalid_contract",
            "continuity contract has an invalid type",
        )
    if not isinstance(contract.schema_version, str) or not contract.schema_version:
        raise ContractFailure(
            "invalid_contract",
            "continuity contract has an invalid schema version",
        )
    if not isinstance(contract.kind, str) or not contract.kind:
        raise ContractFailure(
            "invalid_contract",
            "continuity contract has an invalid kind",
        )
    _require_token(contract.operation_id, "operation_id")
    _validate_workload(contract)
    if not isinstance(contract.authorities, Mapping):
        raise ContractFailure(
            "invalid_authority_declaration",
            "continuity contract authority declarations are invalid",
        )
    for name, declaration in contract.authorities.items():
        _validate_authority_declaration(name, declaration)
    if not isinstance(contract.stages, tuple):
        raise ContractFailure(
            "invalid_contract",
            "continuity contract stages are invalid",
        )
    for stage in contract.stages:
        _validate_stage_shape(stage)


def _validate_stage_shape(stage: StageSpec) -> None:
    if not isinstance(stage, StageSpec):
        raise ContractFailure(
            "invalid_contract",
            "continuity contract contains an invalid stage",
        )
    _require_token(stage.id, "stage id")
    _require_token(stage.adapter, f"stage '{stage.id}' adapter")
    _require_token(stage.operation, f"stage '{stage.id}' operation")
    if not isinstance(stage.requires, tuple):
        raise ContractFailure(
            "invalid_contract",
            f"stage '{stage.id}' dependencies are invalid",
        )
    for dependency in stage.requires:
        _require_token(dependency, f"stage '{stage.id}' dependency")
    if not isinstance(stage.inputs, Mapping):
        raise ContractFailure(
            "invalid_stage_inputs",
            f"stage '{stage.id}' declares invalid inputs",
        )
    for name, value in stage.inputs.items():
        _require_token(name, f"stage '{stage.id}' input")
        _validate_json_value(value, f"stage '{stage.id}' input '{name}'")
    if not isinstance(stage.input_bindings, Mapping):
        raise ContractFailure(
            "invalid_binding",
            f"stage '{stage.id}' input bindings are invalid",
        )
    for name, binding in stage.input_bindings.items():
        _require_token(name, f"stage '{stage.id}' input binding")
        if not isinstance(binding, InputBinding):
            raise ContractFailure(
                "invalid_binding",
                f"stage '{stage.id}' input '{name}' has an invalid binding",
            )
        _require_token(binding.stage, f"stage '{stage.id}' input binding stage")
        _require_token(binding.output, f"stage '{stage.id}' input binding output")
    if not isinstance(stage.publish, frozenset):
        raise ContractFailure(
            "invalid_contract",
            f"stage '{stage.id}' published outputs are invalid",
        )
    for name in stage.publish:
        _require_token(name, f"stage '{stage.id}' published output")
    if not isinstance(stage.evidence_bindings, tuple):
        raise ContractFailure(
            "invalid_evidence_binding",
            f"stage '{stage.id}' evidence bindings are invalid",
        )
    for binding in stage.evidence_bindings:
        if not isinstance(binding, EvidenceBinding):
            raise ContractFailure(
                "invalid_evidence_binding",
                f"stage '{stage.id}' has an invalid evidence binding",
            )
        for value in (binding.stage, binding.name, binding.role):
            _require_token(value, f"stage '{stage.id}' evidence binding")
    if stage.authority is not None:
        if not isinstance(stage.authority, AuthorityRequirement):
            raise ContractFailure(
                "invalid_authority_requirement",
                f"stage '{stage.id}' authority requirement is invalid",
            )
        _require_token(
            stage.authority.logical_ref,
            f"stage '{stage.id}' authority reference",
        )
        _require_token(
            stage.authority.capability,
            f"stage '{stage.id}' authority capability",
        )
        if type(stage.authority.compatibility) is not bool:
            raise ContractFailure(
                "invalid_authority_requirement",
                f"stage '{stage.id}' authority compatibility flag is invalid",
            )
    if stage.recovery_operation is not None:
        _require_token(
            stage.recovery_operation,
            f"stage '{stage.id}' recovery operation",
        )


def _validate_authority_declaration(
    name: object,
    declaration: object,
) -> None:
    _require_token(name, "authority declaration key")
    if not isinstance(declaration, AuthorityDeclaration):
        raise ContractFailure(
            "invalid_authority_declaration",
            f"authority declaration '{name}' is invalid",
        )
    for value, label in (
        (declaration.logical_ref, "logical reference"),
        (declaration.capability, "capability"),
        (declaration.provider, "provider"),
    ):
        _require_token(value, f"authority declaration '{name}' {label}")
    if name != declaration.logical_ref:
        raise ContractFailure(
            "authority_declaration_mismatch",
            f"authority declaration '{name}' has a mismatched logical reference",
        )
    if type(declaration.compatibility) is not bool:
        raise ContractFailure(
            "invalid_authority_declaration",
            f"authority declaration '{name}' compatibility flag is invalid",
        )
    _validate_json_value(
        declaration.config,
        f"authority declaration '{name}' configuration",
    )


def _validate_authority_binding(
    contract: ContinuityContract,
    stage: StageSpec,
) -> None:
    requirement = stage.authority
    if requirement is None:
        raise ContractFailure(
            "invalid_authority_requirement",
            f"stage '{stage.id}' authority requirement is missing",
        )
    declaration = contract.authorities.get(requirement.logical_ref)
    if declaration is None:
        raise ContractFailure(
            "missing_authority_declaration",
            f"stage '{stage.id}' authority declaration is missing",
        )
    if declaration.capability != requirement.capability:
        raise ContractFailure(
            "authority_capability_mismatch",
            f"stage '{stage.id}' authority capability does not match its declaration",
        )
    if declaration.compatibility != requirement.compatibility:
        raise ContractFailure(
            "authority_compatibility_mismatch",
            f"stage '{stage.id}' authority compatibility does not match its declaration",
        )


def _validate_json_value(value: object, label: str) -> None:
    if isinstance(value, Mapping):
        for name, item in value.items():
            if not isinstance(name, str):
                raise ContractFailure(
                    "invalid_contract",
                    f"{label} contains a non-string key",
                )
            _validate_json_value(item, label)
        return
    if isinstance(value, tuple):
        for item in value:
            _validate_json_value(item, label)
        return
    if value is None or isinstance(value, (str, bool, int)):
        return
    if isinstance(value, float) and math.isfinite(value):
        return
    raise ContractFailure(
        "invalid_contract",
        f"{label} contains an unsupported value",
    )


def _validate_workload(contract: ContinuityContract) -> None:
    workload = contract.workload
    if not isinstance(workload, WorkloadIdentity):
        raise ContractFailure(
            "invalid_workload_identity",
            "workload identity has an invalid type",
        )
    for field_name in ("name", "revision"):
        value = getattr(workload, field_name, None)
        if not isinstance(value, str) or not value.strip() or value != value.strip():
            raise ContractFailure(
                "invalid_workload_identity",
                f"workload identity has invalid {field_name}",
            )
    if not is_sha256_digest(getattr(workload, "digest", None)):
        raise ContractFailure(
            "invalid_workload_identity",
            "workload identity has invalid digest",
        )


def _validate_adapter_contract(
    adapter_name: str,
    adapters: Mapping[str, ContinuityAdapter],
) -> _AdapterContract:
    adapter = adapters.get(adapter_name)
    if adapter is None:
        raise ContractFailure(
            "unknown_adapter",
            f"unknown continuity adapter '{adapter_name}'",
        )
    try:
        identity = getattr(adapter, "identity", None)
    except Exception as exc:
        raise ContractFailure(
            "invalid_adapter_identity",
            f"adapter '{adapter_name}' has an invalid identity",
        ) from exc
    if not isinstance(identity, AdapterIdentity):
        raise ContractFailure(
            "invalid_adapter_identity",
            f"adapter '{adapter_name}' has an invalid identity",
        )
    try:
        identity_snapshot = AdapterIdentity(
            name=identity.name,
            distribution=identity.distribution,
            version=identity.version,
            revision=identity.revision,
            contract_version=identity.contract_version,
        )
    except Exception as exc:
        raise ContractFailure(
            "invalid_adapter_identity",
            f"adapter '{adapter_name}' has an invalid identity",
        ) from exc
    if identity_snapshot.name != adapter_name:
        raise ContractFailure(
            "adapter_identity_mismatch",
            f"adapter '{adapter_name}' reported a mismatched identity",
        )
    if identity_snapshot.contract_version != ADAPTER_CONTRACT_VERSION:
        raise ContractFailure(
            "unsupported_adapter_contract",
            f"adapter '{adapter_name}' uses an unsupported contract version",
        )
    for field_name in ("distribution", "version", "revision"):
        value = getattr(identity_snapshot, field_name)
        if not isinstance(value, str) or not value.strip() or value != value.strip():
            raise ContractFailure(
                "invalid_adapter_identity",
                f"adapter '{adapter_name}' has invalid {field_name}",
            )
    try:
        declared_operations = getattr(adapter, "operations", None)
    except Exception as exc:
        raise ContractFailure(
            "invalid_adapter_contract",
            f"adapter '{adapter_name}' declares invalid operations",
        ) from exc
    if not isinstance(declared_operations, frozenset):
        raise ContractFailure(
            "invalid_adapter_contract",
            f"adapter '{adapter_name}' declares invalid operations",
        )
    try:
        operations = tuple(sorted(declared_operations))
    except Exception as exc:
        raise ContractFailure(
            "invalid_adapter_contract",
            f"adapter '{adapter_name}' declares invalid operations",
        ) from exc
    if not all(is_token(operation) for operation in operations):
        raise ContractFailure(
            "invalid_adapter_contract",
            f"adapter '{adapter_name}' declares invalid operations",
        )
    for method_name in ("admit", "execute", "recover"):
        try:
            method = getattr(adapter, method_name, None)
        except Exception as exc:
            raise ContractFailure(
                "invalid_adapter_contract",
                f"adapter '{adapter_name}' does not implement '{method_name}'",
            ) from exc
        if not callable(method):
            raise ContractFailure(
                "invalid_adapter_contract",
                f"adapter '{adapter_name}' does not implement '{method_name}'",
            )
    return identity_snapshot, operations


def _validate_stage_adapter(
    stage: StageSpec,
    adapter_contract: _AdapterContract,
) -> None:
    _, operations = adapter_contract
    if stage.operation not in operations:
        raise ContractFailure(
            "unsupported_operation",
            f"adapter '{stage.adapter}' does not support '{stage.operation}'",
        )
    if (
        stage.recovery_operation is not None
        and stage.recovery_operation not in operations
    ):
        raise ContractFailure(
            "unsupported_recovery",
            f"adapter '{stage.adapter}' does not support recovery operation "
            f"'{stage.recovery_operation}'",
        )


def _validate_binding(
    stage: StageSpec,
    name: str,
    binding: InputBinding,
    by_id: Mapping[str, StageSpec],
    reachable: frozenset[str],
) -> None:
    if binding.stage not in by_id:
        raise ContractFailure(
            "unknown_binding",
            f"stage '{stage.id}' input '{name}' binds unknown stage '{binding.stage}'",
        )
    if binding.stage not in reachable:
        raise ContractFailure(
            "unordered_binding",
            f"stage '{stage.id}' input '{name}' is not bound to a dependency",
        )
    if binding.output not in by_id[binding.stage].publish:
        raise ContractFailure(
            "unpublished_binding",
            f"stage '{stage.id}' input '{name}' binds unpublished output "
            f"'{binding.output}' from stage '{binding.stage}'",
        )


def _validate_evidence_binding(
    stage: StageSpec,
    binding: EvidenceBinding,
    by_id: Mapping[str, StageSpec],
    reachable: frozenset[str],
) -> None:
    if binding.stage not in by_id:
        raise ContractFailure(
            "unknown_evidence_binding",
            f"stage '{stage.id}' binds evidence from unknown stage '{binding.stage}'",
        )
    if binding.stage not in reachable:
        raise ContractFailure(
            "unordered_evidence_binding",
            f"stage '{stage.id}' evidence is not bound to a dependency",
        )


def _dependencies(
    stage_id: str,
    by_id: Mapping[str, StageSpec],
) -> frozenset[str]:
    found: set[str] = set()
    pending = list(by_id[stage_id].requires)
    while pending:
        dependency = pending.pop()
        if dependency in found or dependency not in by_id:
            continue
        found.add(dependency)
        pending.extend(by_id[dependency].requires)
    return frozenset(found)


def _topological_order(by_id: Mapping[str, StageSpec]) -> tuple[str, ...]:
    indegree = {stage_id: 0 for stage_id in by_id}
    dependants = {stage_id: [] for stage_id in by_id}
    for stage in by_id.values():
        for dependency in stage.requires:
            indegree[stage.id] += 1
            dependants[dependency].append(stage.id)

    ready = [stage_id for stage_id, count in indegree.items() if count == 0]
    heapq.heapify(ready)
    order: list[str] = []
    while ready:
        stage_id = heapq.heappop(ready)
        order.append(stage_id)
        for dependant in sorted(dependants[stage_id]):
            indegree[dependant] -= 1
            if indegree[dependant] == 0:
                heapq.heappush(ready, dependant)

    if len(order) != len(by_id):
        raise ContractFailure(
            "dependency_cycle",
            "continuity contract contains a dependency cycle",
        )
    return tuple(order)


def _require_token(value: object, label: str) -> None:
    if not is_token(value):
        raise ContractFailure(
            "invalid_contract",
            f"{label} has an invalid format",
        )
