"""Version-neutral values used by continuity API codecs."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from ..json_values import freeze_json
from ..models import EvidenceBinding

API_GROUP = "continuity.hyopsproject.github.io"
API_KIND = "ContinuityContract"


@dataclass(frozen=True)
class ObjectMeta:
    name: str
    namespace: str = "default"
    uid: str = ""
    generation: int = 0
    extra: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "extra", freeze_json(self.extra))


@dataclass(frozen=True)
class LocalObjectReference:
    kind: str
    name: str
    api_group: str = ""


@dataclass(frozen=True)
class ApiWorkload:
    name: str
    revision: str
    digest: str
    ref: LocalObjectReference | None = None


@dataclass(frozen=True)
class ApiPolicy:
    failure_action: str = "Recover"
    unverifiable_action: str = "Block"
    terminal_evidence: str = "Required"


@dataclass(frozen=True)
class AuthoritySpec:
    name: str
    capability: str
    provider: str
    parameters_ref: LocalObjectReference | None = None
    compatibility: bool = False


@dataclass(frozen=True)
class InputBindingSpec:
    name: str
    stage: str
    output: str


@dataclass(frozen=True)
class RecoverySetSpec:
    name: str
    stage: str
    evidence: str
    role: str


@dataclass(frozen=True)
class ApiStage:
    id: str
    adapter: str
    operation: str
    requires: tuple[str, ...] = ()
    parameters_ref: LocalObjectReference | None = None
    input_bindings: tuple[InputBindingSpec, ...] = ()
    publish: frozenset[str] = frozenset()
    recovery_sets: frozenset[str] = frozenset()
    authority_ref: str | None = None
    recovery_operation: str | None = None
    destructive: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.requires, tuple):
            raise TypeError("stage dependencies must be a tuple")
        if not isinstance(self.input_bindings, tuple):
            raise TypeError("stage input bindings must be a tuple")
        if not isinstance(self.publish, frozenset):
            raise TypeError("stage published outputs must be a frozenset")
        if not isinstance(self.recovery_sets, frozenset):
            raise TypeError("stage recovery sets must be a frozenset")
        object.__setattr__(self, "requires", tuple(sorted(self.requires)))
        object.__setattr__(
            self,
            "input_bindings",
            tuple(sorted(self.input_bindings, key=lambda item: item.name)),
        )


@dataclass(frozen=True)
class ApiSpec:
    workload: ApiWorkload
    policy: ApiPolicy
    stages: tuple[ApiStage, ...]
    authorities: tuple[AuthoritySpec, ...] = ()
    recovery_sets: tuple[RecoverySetSpec, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.stages, tuple):
            raise TypeError("contract stages must be a tuple")
        if not isinstance(self.authorities, tuple):
            raise TypeError("contract authorities must be a tuple")
        if not isinstance(self.recovery_sets, tuple):
            raise TypeError("contract recovery sets must be a tuple")
        object.__setattr__(
            self,
            "stages",
            tuple(sorted(self.stages, key=lambda item: item.id)),
        )
        object.__setattr__(
            self,
            "authorities",
            tuple(sorted(self.authorities, key=lambda item: item.name)),
        )
        object.__setattr__(
            self,
            "recovery_sets",
            tuple(sorted(self.recovery_sets, key=lambda item: item.name)),
        )

    def producer_evidence_by_stage(self) -> dict[str, dict[str, str]]:
        """Index a validated spec's output evidence names and roles by producer."""
        outputs: dict[str, dict[str, str]] = {stage.id: {} for stage in self.stages}
        for recovery_set in self.recovery_sets:
            outputs[recovery_set.stage][recovery_set.evidence] = recovery_set.role
        return outputs

    def recovery_bindings_by_stage(self) -> dict[str, tuple[EvidenceBinding, ...]]:
        """Resolve recovery set names to their declared producers in a validated spec."""
        sets = {
            item.name: EvidenceBinding(item.stage, item.evidence, item.role)
            for item in self.recovery_sets
        }
        return {
            stage.id: tuple(sets[name] for name in sorted(stage.recovery_sets))
            for stage in self.stages
        }


@dataclass(frozen=True)
class ApiCondition:
    type: str
    status: str
    reason: str
    message: str
    last_transition_time: str
    observed_generation: int = 0


@dataclass(frozen=True)
class RecoverySetIdentity:
    name: str
    evidence: str
    role: str
    digest: str


@dataclass(frozen=True)
class TerminalEvidenceReference:
    api_group: str
    kind: str
    name: str
    digest: str


@dataclass(frozen=True)
class ApiStatus:
    observed_generation: int = 0
    phase: str = "Pending"
    conditions: tuple[ApiCondition, ...] = ()
    recovery_sets: tuple[RecoverySetIdentity, ...] = ()
    terminal_evidence: TerminalEvidenceReference | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.conditions, tuple):
            raise TypeError("status conditions must be a tuple")
        if not isinstance(self.recovery_sets, tuple):
            raise TypeError("status recovery sets must be a tuple")
        object.__setattr__(
            self,
            "conditions",
            tuple(sorted(self.conditions, key=lambda item: item.type)),
        )
        object.__setattr__(
            self,
            "recovery_sets",
            tuple(sorted(self.recovery_sets, key=lambda item: item.name)),
        )


@dataclass(frozen=True)
class ApiResource:
    metadata: ObjectMeta
    spec: ApiSpec
    status: ApiStatus | None = None
