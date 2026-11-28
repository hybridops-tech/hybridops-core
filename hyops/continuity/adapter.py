"""Adapter boundary for continuity contract stages."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Protocol

from hyops.authority.models import (
    AuthorityContext,
    AuthorityDeclaration,
    AuthorityReceipt,
    AuthorityRequirement,
)

from .models import (
    AdapterIdentity,
    AdapterRequest,
    AdmissionResult,
    ExecutionResult,
    RecoveryRequest,
    RecoveryResult,
)


class ContinuityAdapter(Protocol):
    identity: AdapterIdentity
    operations: frozenset[str]

    def admit(self, request: AdapterRequest) -> AdmissionResult: ...

    def execute(self, request: AdapterRequest) -> ExecutionResult: ...

    def recover(self, request: RecoveryRequest) -> RecoveryResult: ...


class AuthorityGate(Protocol):
    def enforce(
        self,
        requirement: AuthorityRequirement,
        declarations: Mapping[str, AuthorityDeclaration],
        context: AuthorityContext,
    ) -> AuthorityReceipt: ...
