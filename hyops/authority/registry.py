"""Authority provider registration without product branching."""

from __future__ import annotations

import re
from dataclasses import dataclass

from hyops import __version__

from .models import (
    AUTHORITY_PROVIDER_CONTRACT_VERSION,
    AuthorityProviderIdentity,
)
from .provider import AuthorityProvider

_TOKEN_RE = re.compile(r"^[a-z][a-z0-9_-]{0,63}$")


@dataclass(frozen=True)
class AuthorityProviderRegistration:
    name: str
    capabilities: frozenset[str]
    provider: AuthorityProvider
    identity: AuthorityProviderIdentity


def _direct_identity(provider: AuthorityProvider) -> AuthorityProviderIdentity:
    provider_type = type(provider)
    is_core_provider = provider_type.__module__.startswith("hyops.")
    return AuthorityProviderIdentity(
        source="direct",
        distribution="hybridops-core" if is_core_provider else "unknown",
        version=__version__ if is_core_provider else "unknown",
        entry_point=f"{provider_type.__module__}:{provider_type.__qualname__}",
    )


class AuthorityProviderRegistry:
    def __init__(self) -> None:
        self._registrations: dict[str, AuthorityProviderRegistration] = {}
        self._discovery_error = ""

    def register(
        self,
        provider: AuthorityProvider,
        *,
        identity: AuthorityProviderIdentity | None = None,
    ) -> None:
        name = getattr(provider, "name", None)
        if not isinstance(name, str) or not name:
            raise ValueError("authority provider name is required")
        if name != name.strip().lower():
            raise ValueError(
                "authority provider name must use canonical lowercase form "
                "without surrounding whitespace"
            )
        if not _TOKEN_RE.fullmatch(name):
            raise ValueError(f"authority provider name has an invalid format: {name}")
        raw_capabilities = getattr(provider, "capabilities", None)
        if not isinstance(raw_capabilities, frozenset):
            raise TypeError(
                f"authority provider '{name}' capabilities must be a frozenset"
            )
        if not raw_capabilities:
            raise ValueError(
                f"authority provider '{name}' must declare non-empty capabilities"
            )
        invalid_capabilities = sorted(
            repr(capability)
            for capability in raw_capabilities
            if not isinstance(capability, str)
            or capability != capability.strip().lower()
            or not _TOKEN_RE.fullmatch(capability)
        )
        if invalid_capabilities:
            raise ValueError(
                f"authority provider '{name}' has invalid capabilities: "
                f"{', '.join(invalid_capabilities)}"
            )
        if not callable(getattr(provider, "validate_configuration", None)):
            raise TypeError(
                f"authority provider '{name}' must implement validate_configuration"
            )
        if not callable(getattr(provider, "evaluate", None)):
            raise TypeError(f"authority provider '{name}' must implement evaluate")
        has_interval_check = callable(getattr(provider, "interval_verifiable", None))
        has_interval_evaluation = callable(
            getattr(provider, "evaluate_interval", None)
        )
        if has_interval_check != has_interval_evaluation:
            raise TypeError(
                f"authority provider '{name}' must implement both interval_verifiable "
                "and evaluate_interval"
            )
        provider_identity = identity or _direct_identity(provider)
        self._validate_identity(provider_identity, name)
        if name in self._registrations:
            raise ValueError(f"authority provider already registered: {name}")
        self._registrations[name] = AuthorityProviderRegistration(
            name=name,
            capabilities=raw_capabilities,
            provider=provider,
            identity=provider_identity,
        )

    @staticmethod
    def _validate_identity(
        identity: AuthorityProviderIdentity,
        provider_name: str,
    ) -> None:
        if not isinstance(identity, AuthorityProviderIdentity):
            raise TypeError(
                f"authority provider '{provider_name}' identity is invalid"
            )
        for field_name in ("source", "distribution", "version", "entry_point"):
            value = getattr(identity, field_name)
            if not isinstance(value, str) or not value.strip() or value != value.strip():
                raise ValueError(
                    f"authority provider '{provider_name}' identity {field_name} "
                    "must be a non-empty canonical string"
                )
        if identity.contract_version != AUTHORITY_PROVIDER_CONTRACT_VERSION:
            raise ValueError(
                f"authority provider '{provider_name}' uses unsupported contract "
                f"version '{identity.contract_version}'"
            )

    def resolve(self, name: str) -> AuthorityProvider:
        return self.registration(name).provider

    def registration(self, name: str) -> AuthorityProviderRegistration:
        token = str(name or "").strip().lower()
        registration = self._registrations.get(token)
        if registration is None:
            available = ", ".join(sorted(self._registrations)) or "none"
            raise ValueError(
                f"unknown authority provider '{token or '<empty>'}' "
                f"(registered: {available})"
            )
        return registration

    def names(self) -> tuple[str, ...]:
        return tuple(sorted(self._registrations))

    def clone(self) -> AuthorityProviderRegistry:
        registry = AuthorityProviderRegistry()
        registry._registrations = dict(self._registrations)
        registry._discovery_error = self._discovery_error
        return registry

    def replace_from(self, registry: AuthorityProviderRegistry) -> None:
        if not isinstance(registry, AuthorityProviderRegistry):
            raise TypeError("authority provider registry replacement is invalid")
        self._registrations = dict(registry._registrations)
        self._discovery_error = registry._discovery_error

    def record_discovery_error(self, detail: str) -> None:
        message = str(detail or "").strip()
        self._discovery_error = message or "unknown authority provider discovery failure"

    def mark_discovery_complete(self) -> None:
        self._discovery_error = ""

    def require_discovery_complete(self) -> None:
        if self._discovery_error:
            raise RuntimeError(
                "authority provider discovery is incomplete: "
                f"{self._discovery_error}"
            )
