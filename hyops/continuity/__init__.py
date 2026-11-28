"""Continuity contract execution independent of infrastructure adapters."""

from .adapter import ContinuityAdapter
from .engine import ContinuityEngine
from .errors import ContractFailure, TerminalPersistenceError
from .models import (
    AdapterIdentity,
    AdapterRequest,
    AdmissionResult,
    AuthorityAdmission,
    AuthorityProviderProvenance,
    ContinuityContract,
    ControllerIdentity,
    EvidenceBinding,
    EvidenceIdentity,
    ExecutionResult,
    InputBinding,
    OutputIdentity,
    RecoveryRequest,
    RecoveryResult,
    StageSpec,
    TerminalRecord,
    WorkloadIdentity,
)

__all__ = [
    "AdapterIdentity",
    "AdapterRequest",
    "AdmissionResult",
    "AuthorityAdmission",
    "AuthorityProviderProvenance",
    "ContinuityAdapter",
    "ContinuityContract",
    "ContinuityEngine",
    "ContractFailure",
    "ControllerIdentity",
    "EvidenceBinding",
    "EvidenceIdentity",
    "ExecutionResult",
    "InputBinding",
    "OutputIdentity",
    "RecoveryRequest",
    "RecoveryResult",
    "StageSpec",
    "TerminalPersistenceError",
    "TerminalRecord",
    "WorkloadIdentity",
]
