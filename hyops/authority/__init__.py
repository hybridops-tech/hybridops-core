"""Provider-neutral operation authority contracts."""

from typing import Any

from .models import (
    AUTHORITY_PROVIDER_CONTRACT_VERSION,
    AuthorityContext,
    AuthorityDeclaration,
    AuthorityEvaluation,
    AuthorityIntervalEvaluation,
    AuthorityIntervalReceipt,
    AuthorityObservation,
    AuthorityObservationPolicy,
    AuthorityProviderIdentity,
    AuthorityReceipt,
    AuthorityRequirement,
    AuthoritySession,
)

__all__ = [
    "AUTHORITY_PROVIDER_CONTRACT_VERSION",
    "AuthorityContext",
    "AuthorityDeclaration",
    "AuthorityEvaluation",
    "AuthorityIntervalEvaluation",
    "AuthorityIntervalReceipt",
    "AuthorityObservation",
    "AuthorityObservationPolicy",
    "AuthorityProviderIdentity",
    "AuthorityReceipt",
    "AuthorityRequirement",
    "AuthorityResolver",
    "AuthoritySession",
    "default_authority_registry",
]


def __getattr__(name: str) -> Any:
    if name == "AuthorityResolver":
        from .resolver import AuthorityResolver

        return AuthorityResolver
    if name == "default_authority_registry":
        from .resolver import default_authority_registry

        return default_authority_registry
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
