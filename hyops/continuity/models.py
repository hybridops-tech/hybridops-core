"""Typed continuity contract values and terminal evidence."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from types import MappingProxyType
from typing import Any

from hyops.authority.models import (
    AuthorityDeclaration,
    AuthorityReceipt,
    AuthorityRequirement,
)

from .json_values import digest_json as _digest_json
from .json_values import freeze_json as _freeze_json
from .json_values import thaw_json as _thaw_json

ADAPTER_CONTRACT_VERSION = "1"
CONTINUITY_CONTRACT_SCHEMA_VERSION = "1"
CONTINUITY_KIND = "ContinuityContract"
CONTROLLER_CONTRACT_VERSION = "1"
TERMINAL_RECORD_SCHEMA_VERSION = "1"


@dataclass(frozen=True)
class AdapterIdentity:
    """Installed code identity responsible for a stage operation."""

    name: str
    distribution: str
    version: str
    revision: str
    contract_version: str = ADAPTER_CONTRACT_VERSION

    def to_evidence(self) -> dict[str, str]:
        return {
            "name": self.name,
            "distribution": self.distribution,
            "version": self.version,
            "revision": self.revision,
            "contract_version": self.contract_version,
        }


@dataclass(frozen=True)
class ControllerIdentity:
    """Controller build identity recorded against every operation."""

    distribution: str
    version: str
    revision: str
    contract_version: str = CONTROLLER_CONTRACT_VERSION

    def to_evidence(self) -> dict[str, str]:
        return {
            "distribution": self.distribution,
            "version": self.version,
            "revision": self.revision,
            "contract_version": self.contract_version,
        }


@dataclass(frozen=True)
class WorkloadIdentity:
    """Exact workload revision governed by a continuity contract."""

    name: str
    revision: str
    digest: str

    def to_evidence(self) -> dict[str, str]:
        return {
            "name": self.name,
            "revision": self.revision,
            "digest": self.digest,
        }


@dataclass(frozen=True)
class EvidenceIdentity:
    """Content identity for recovery material or operation evidence."""

    name: str
    role: str
    digest: str

    def to_evidence(self) -> dict[str, str]:
        return {
            "name": self.name,
            "role": self.role,
            "digest": self.digest,
        }


@dataclass(frozen=True)
class EvidenceBinding:
    """Bind a stage to exact evidence from a predecessor."""

    stage: str
    name: str
    role: str


@dataclass(frozen=True)
class OutputIdentity:
    """Content identity for a published stage output."""

    name: str
    digest: str

    def to_evidence(self) -> dict[str, str]:
        return {
            "name": self.name,
            "digest": self.digest,
        }


@dataclass(frozen=True)
class AuthorityProviderProvenance:
    """Secret-free build identity for an admitted authority provider."""

    source: str
    distribution: str
    version: str
    entry_point: str
    contract_version: str

    def to_evidence(self) -> dict[str, str]:
        return {
            "source": self.source,
            "distribution": self.distribution,
            "version": self.version,
            "entry_point": self.entry_point,
            "contract_version": self.contract_version,
        }


@dataclass(frozen=True)
class AuthorityAdmission:
    """Secret-free identity of an admitted operation authority."""

    logical_ref: str
    capability: str
    provider: str
    provider_identity: AuthorityProviderProvenance
    decision: str = "admitted"

    def to_evidence(self) -> dict[str, Any]:
        return {
            "logical_authority": self.logical_ref,
            "capability": self.capability,
            "provider": self.provider,
            "provider_identity": self.provider_identity.to_evidence(),
            "decision": self.decision,
        }


@dataclass(frozen=True)
class InputBinding:
    """Bind one stage input to a published predecessor output."""

    stage: str
    output: str


@dataclass(frozen=True)
class StageSpec:
    """One ordered operation in a continuity contract."""

    id: str
    adapter: str
    operation: str
    requires: tuple[str, ...] = ()
    inputs: Mapping[str, Any] = field(default_factory=dict)
    input_bindings: Mapping[str, InputBinding] = field(default_factory=dict)
    publish: frozenset[str] = frozenset()
    evidence_bindings: tuple[EvidenceBinding, ...] = ()
    authority: AuthorityRequirement | None = None
    recovery_operation: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.requires, tuple):
            raise TypeError("stage dependencies must be a tuple")
        if not isinstance(self.inputs, Mapping):
            raise TypeError("stage inputs must be a mapping")
        if not isinstance(self.input_bindings, Mapping):
            raise TypeError("stage input bindings must be a mapping")
        if not isinstance(self.publish, frozenset):
            raise TypeError("stage published outputs must be a frozenset")
        if not isinstance(self.evidence_bindings, tuple):
            raise TypeError("stage evidence bindings must be a tuple")
        object.__setattr__(self, "inputs", _freeze_json(self.inputs))
        object.__setattr__(
            self,
            "input_bindings",
            MappingProxyType(dict(self.input_bindings)),
        )

    def to_digest_payload(self) -> dict[str, Any]:
        authority = None
        if self.authority is not None:
            authority = {
                "logical_ref": self.authority.logical_ref,
                "capability": self.authority.capability,
                "compatibility": self.authority.compatibility,
            }
        return {
            "id": self.id,
            "adapter": self.adapter,
            "operation": self.operation,
            "requires": list(self.requires),
            "inputs": _thaw_json(self.inputs),
            "input_bindings": {
                name: {"stage": binding.stage, "output": binding.output}
                for name, binding in sorted(self.input_bindings.items())
            },
            "publish": sorted(self.publish),
            "evidence_bindings": [
                {
                    "stage": binding.stage,
                    "name": binding.name,
                    "role": binding.role,
                }
                for binding in self.evidence_bindings
            ],
            "authority": authority,
            "recovery_operation": self.recovery_operation,
        }


@dataclass(frozen=True)
class ContinuityContract:
    """A versioned continuity operation and its authority declarations."""

    operation_id: str
    workload: WorkloadIdentity
    stages: tuple[StageSpec, ...]
    authorities: Mapping[str, AuthorityDeclaration] = field(default_factory=dict)
    schema_version: str = CONTINUITY_CONTRACT_SCHEMA_VERSION
    kind: str = CONTINUITY_KIND

    def __post_init__(self) -> None:
        if not isinstance(self.stages, tuple):
            raise TypeError("continuity contract stages must be a tuple")
        if not isinstance(self.authorities, Mapping):
            raise TypeError("continuity contract authorities must be a mapping")
        authorities: dict[str, AuthorityDeclaration] = {}
        for name, declaration in self.authorities.items():
            if isinstance(declaration, AuthorityDeclaration):
                declaration = replace(
                    declaration,
                    config=_freeze_json(declaration.config),
                )
            authorities[name] = declaration
        object.__setattr__(
            self,
            "authorities",
            MappingProxyType(authorities),
        )

    def digest(self) -> str:
        authorities = {
            name: {
                "logical_ref": declaration.logical_ref,
                "capability": declaration.capability,
                "provider": declaration.provider,
                "config": _thaw_json(declaration.config),
                "compatibility": declaration.compatibility,
            }
            for name, declaration in sorted(self.authorities.items())
        }
        return _digest_json(
            {
                "schema_version": self.schema_version,
                "kind": self.kind,
                "operation_id": self.operation_id,
                "workload": self.workload.to_evidence(),
                "authorities": authorities,
                "stages": [stage.to_digest_payload() for stage in self.stages],
            }
        )


@dataclass(frozen=True)
class AdapterRequest:
    """Resolved stage request passed to an adapter."""

    operation_id: str
    stage_id: str
    operation: str
    inputs: Mapping[str, Any]
    authority_receipt: AuthorityReceipt | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "inputs", _freeze_json(self.inputs))


@dataclass(frozen=True)
class AdmissionResult:
    """Adapter decision made before stage mutation."""

    allowed: bool
    reason_code: str = ""


@dataclass(frozen=True)
class ExecutionResult:
    """Adapter outputs returned after a successful stage operation."""

    outputs: Mapping[str, Any] = field(default_factory=dict)
    evidence: tuple[EvidenceIdentity, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "outputs", _freeze_json(self.outputs))
        object.__setattr__(self, "evidence", tuple(self.evidence))


@dataclass(frozen=True)
class RecoveryRequest:
    """Completed stage supplied to its adapter for recovery."""

    operation_id: str
    stage_id: str
    operation: str
    recovery_operation: str
    inputs: Mapping[str, Any]
    outputs: Mapping[str, Any]

    def __post_init__(self) -> None:
        object.__setattr__(self, "inputs", _freeze_json(self.inputs))
        object.__setattr__(self, "outputs", _freeze_json(self.outputs))


@dataclass(frozen=True)
class RecoveryResult:
    """Adapter recovery result."""

    succeeded: bool
    reason_code: str = ""


@dataclass(frozen=True)
class StageRecord:
    """Terminal state for one attempted stage."""

    stage_id: str
    adapter: AdapterIdentity
    adapter_operations: tuple[str, ...]
    operation: str
    status: str
    reason_code: str = ""
    adapter_reason_code: str = ""
    result: str = ""
    authority_receipt: AuthorityAdmission | None = None
    outputs: tuple[OutputIdentity, ...] = ()
    evidence: tuple[EvidenceIdentity, ...] = ()
    recovery_status: str = "not_required"
    recovery_reason_code: str = ""
    adapter_recovery_reason_code: str = ""
    recovery_result: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "adapter_operations",
            tuple(self.adapter_operations),
        )
        object.__setattr__(self, "outputs", tuple(self.outputs))
        object.__setattr__(self, "evidence", tuple(self.evidence))

    def to_evidence(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "stage_id": self.stage_id,
            "adapter": self.adapter.to_evidence(),
            "adapter_operations": list(self.adapter_operations),
            "operation": self.operation,
            "status": self.status,
            "recovery_status": self.recovery_status,
        }
        if self.reason_code:
            payload["reason_code"] = self.reason_code
        if self.adapter_reason_code:
            payload["adapter_reason_code"] = self.adapter_reason_code
        if self.result:
            payload["result"] = self.result
        if self.authority_receipt is not None:
            payload["authority_receipt"] = self.authority_receipt.to_evidence()
        if self.outputs:
            payload["outputs"] = [item.to_evidence() for item in self.outputs]
        if self.evidence:
            payload["evidence"] = [item.to_evidence() for item in self.evidence]
        if self.recovery_reason_code:
            payload["recovery_reason_code"] = self.recovery_reason_code
        if self.adapter_recovery_reason_code:
            payload["adapter_recovery_reason_code"] = self.adapter_recovery_reason_code
        if self.recovery_result:
            payload["recovery_result"] = self.recovery_result
        return payload


@dataclass(frozen=True)
class TerminalRecord:
    """Single terminal record for a continuity operation."""

    operation_id: str
    contract_schema_version: str
    contract_digest: str
    controller: ControllerIdentity
    workload: WorkloadIdentity
    status: str
    closure: str
    reason_code: str
    result: str
    started_at: str
    completed_at: str
    stages: tuple[StageRecord, ...]
    schema_version: str = TERMINAL_RECORD_SCHEMA_VERSION
    kind: str = "ContinuityOperationRecord"

    def __post_init__(self) -> None:
        object.__setattr__(self, "stages", tuple(self.stages))

    def to_evidence(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "kind": self.kind,
            "operation_id": self.operation_id,
            "contract": {
                "schema_version": self.contract_schema_version,
                "digest": self.contract_digest,
            },
            "controller": self.controller.to_evidence(),
            "workload": self.workload.to_evidence(),
            "status": self.status,
            "closure": self.closure,
            "reason_code": self.reason_code,
            "result": self.result,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "stages": [stage.to_evidence() for stage in self.stages],
        }


def json_digest(value: Any) -> str:
    """Return the canonical digest of a JSON value."""

    return _digest_json(value)
