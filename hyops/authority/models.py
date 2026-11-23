"""Typed values shared by authority providers and their resolver."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

AUTHORITY_PROVIDER_CONTRACT_VERSION = "1"


@dataclass(frozen=True)
class AuthorityProviderIdentity:
    """Installed code identity responsible for an authority decision."""

    source: str
    distribution: str
    version: str
    entry_point: str
    contract_version: str = AUTHORITY_PROVIDER_CONTRACT_VERSION

    def to_evidence(self) -> dict[str, str]:
        return {
            "source": self.source,
            "distribution": self.distribution,
            "version": self.version,
            "entry_point": self.entry_point,
            "contract_version": self.contract_version,
        }


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
    observation: AuthorityObservation | None = None


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
    provider_identity: AuthorityProviderIdentity
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
            "provider_identity": self.provider_identity.to_evidence(),
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
    provider_identity: AuthorityProviderIdentity
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
            "provider_identity": self.provider_identity.to_evidence(),
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
