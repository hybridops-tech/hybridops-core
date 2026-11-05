"""Typed values shared by authority providers and their resolver."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping


@dataclass(frozen=True)
class AuthorityDeclaration:
    """A logical authority bound to a configured provider."""

    logical_ref: str
    capability: str
    provider: str
    config: Mapping[str, Any] = field(default_factory=dict)
    compatibility: bool = False


@dataclass(frozen=True)
class AuthorityRequirement:
    """The logical authority and capability required by one operation."""

    logical_ref: str
    capability: str
    compatibility: bool = False


@dataclass(frozen=True)
class AuthorityObservationPolicy:
    """How one operation treats authority observations across dispatch."""

    expected_change: str
    on_unverifiable: str


@dataclass(frozen=True)
class AuthorityContext:
    """Runtime inputs available to every authority provider."""

    runtime_root: Path
    state_root: Path
    env: Mapping[str, str]
    assumed_state_ok: frozenset[str] = frozenset()


@dataclass(frozen=True)
class AuthorityEvaluation:
    """Secret-free provider evaluation returned to the generic resolver."""

    healthy: bool
    state: str
    result: str
    instance: str = ""
    endpoint: str = ""
    revision: str = ""
    freshness: Mapping[str, Any] = field(default_factory=dict)
    observation: "AuthorityObservation | None" = None


@dataclass(frozen=True)
class AuthorityObservation:
    """Secret-free, provider-produced observation of one authority scope."""

    token: str
    observed_at: str
    scope: str
    strength: str
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def to_evidence(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "token": self.token,
            "observed_at": self.observed_at,
            "scope": self.scope,
            "strength": self.strength,
        }
        if self.metadata:
            payload["metadata"] = dict(self.metadata)
        return payload


@dataclass(frozen=True)
class AuthorityIntervalEvaluation:
    """Provider verdict for the governed interval and completion read."""

    interval_status: str
    completion_status: str
    result: str
    detection_strength: str
    freshness_basis: str


@dataclass(frozen=True)
class AuthorityIntervalReceipt:
    """Runtime decision and evidence for authority continuity across dispatch."""

    logical_ref: str
    capability: str
    provider: str
    expected_change: str
    on_unverifiable: str
    interval_status: str
    completion_status: str
    decision: str
    result: str
    detection_strength: str
    freshness_basis: str
    before: AuthorityObservation | None = None
    after: AuthorityObservation | None = None

    def to_evidence(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "logical_authority": self.logical_ref,
            "capability": self.capability,
            "provider": self.provider,
            "expected_change": self.expected_change,
            "on_unverifiable": self.on_unverifiable,
            "interval_status": self.interval_status,
            "completion_status": self.completion_status,
            "decision": self.decision,
            "result": self.result,
            "detection_strength": self.detection_strength,
            "freshness_basis": self.freshness_basis,
        }
        if self.before is not None:
            payload["before"] = self.before.to_evidence()
        if self.after is not None:
            payload["after"] = self.after.to_evidence()
        return payload


@dataclass(frozen=True)
class AuthorityReceipt:
    """Attributable evidence that an operation authority was admitted."""

    logical_ref: str
    capability: str
    provider: str
    state: str
    result: str
    instance: str = ""
    endpoint: str = ""
    revision: str = ""
    freshness: Mapping[str, Any] = field(default_factory=dict)
    observation: AuthorityObservation | None = None

    def to_evidence(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "logical_authority": self.logical_ref,
            "capability": self.capability,
            "provider": self.provider,
            "verified_state": self.state,
            "result": self.result,
        }
        if self.instance:
            payload["instance"] = self.instance
        if self.endpoint:
            payload["endpoint"] = self.endpoint
        if self.revision:
            payload["revision"] = self.revision
        if self.freshness:
            payload["freshness"] = dict(self.freshness)
        if self.observation is not None:
            payload["observation"] = self.observation.to_evidence()
        return payload


@dataclass(frozen=True)
class AuthoritySession:
    """Transient authority binding retained only for one dispatch interval."""

    requirement: AuthorityRequirement
    declaration: AuthorityDeclaration
    context: AuthorityContext
    admission: AuthorityReceipt


@dataclass(frozen=True)
class ObservationSource:
    """Distinguishes observation source and provenance for emergency reconciliation."""

    source_type: str  # "declared", "controller_cache", "live_device", "imported"
    freshness_basis: str  # "verified", "inferred", "unverifiable"
    last_known_update: str  # ISO 8601 timestamp or empty
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def to_evidence(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "source_type": self.source_type,
            "freshness_basis": self.freshness_basis,
        }
        if self.last_known_update:
            payload["last_known_update"] = self.last_known_update
        if self.metadata:
            payload["metadata"] = dict(self.metadata)
        return payload


@dataclass(frozen=True)
class AuthorityTransitionDecision:
    """Explicit governance decision to use provisional observation during reconciliation."""

    decision_id: str  # Unique identifier for this decision
    timestamp: str  # ISO 8601 when decision was made
    decision_type: str  # "provisional_use", "keep_declared", "update_declared"
    rationale: str  # Why this decision was made
    authorized_by: str  # Operator or policy that authorized this decision
    provisional_observation: AuthorityObservation | None = None
    authorized_operations: frozenset[str] = frozenset()  # Operations this observation may authorize
    forbidden_operations: frozenset[str] = frozenset()  # Operations this observation cannot authorize

    def to_evidence(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "decision_id": self.decision_id,
            "timestamp": self.timestamp,
            "decision_type": self.decision_type,
            "rationale": self.rationale,
            "authorized_by": self.authorized_by,
        }
        if self.provisional_observation is not None:
            payload["provisional_observation"] = self.provisional_observation.to_evidence()
        if self.authorized_operations:
            payload["authorized_operations"] = sorted(self.authorized_operations)
        if self.forbidden_operations:
            payload["forbidden_operations"] = sorted(self.forbidden_operations)
        return payload


@dataclass(frozen=True)
class AuthorityTransitionRecord:
    """Runtime evidence that authority transitioned during emergency reconciliation."""

    logical_ref: str
    capability: str
    provider: str
    # State before transition
    declared_authority: AuthorityObservation  # What the declared intent says
    controller_cache: AuthorityObservation | None  # Last known controller observation, if any
    live_device_state: AuthorityObservation | None  # Fresh device observation during emergency
    # Decision and transition
    detected_disagreement: bool  # Whether competing observations were known to exist
    transition_decision: AuthorityTransitionDecision | None  # Explicit governance decision, if any
    transition_type: str  # "no_transition", "provisional_use", "rollback", "permanent_update"
    # Return to normal authority
    return_to_declared_at: str = ""  # ISO 8601 when/if transition ended
    return_condition_met: bool = False  # Whether return condition was satisfied
    return_result: str = ""  # Detail about return condition

    def to_evidence(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "logical_authority": self.logical_ref,
            "capability": self.capability,
            "provider": self.provider,
            "declared_authority": self.declared_authority.to_evidence(),
            "detected_disagreement": self.detected_disagreement,
            "transition_type": self.transition_type,
        }
        if self.controller_cache is not None:
            payload["controller_cache"] = self.controller_cache.to_evidence()
        if self.live_device_state is not None:
            payload["live_device_state"] = self.live_device_state.to_evidence()
        if self.transition_decision is not None:
            payload["transition_decision"] = self.transition_decision.to_evidence()
        if self.return_to_declared_at:
            payload["return_to_declared_at"] = self.return_to_declared_at
            payload["return_condition_met"] = self.return_condition_met
            if self.return_result:
                payload["return_result"] = self.return_result
        return payload


@dataclass(frozen=True)
class AuthorityTransitionPolicy:
    """Policy governing authority transitions during emergency reconciliation."""

    allow_provisional_use: bool  # Whether provisional observation use is permitted
    require_explicit_decision: bool  # Whether operator decision is required for provisional use
    max_provisional_duration_s: int  # Maximum time provisional observation may be used (0 = unlimited)
    failure_mode: str  # "fail_closed" (default), "provisional_ok", "continue"
    record_unverifiable: bool  # Whether to record when freshness cannot be verified
