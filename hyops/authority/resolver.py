"""Resolve logical operation requirements through registered providers."""

from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import UTC, datetime

from .models import (
    AuthorityContext,
    AuthorityDeclaration,
    AuthorityEvaluation,
    AuthorityIntervalEvaluation,
    AuthorityIntervalReceipt,
    AuthorityObservation,
    AuthorityObservationPolicy,
    AuthorityReceipt,
    AuthorityRequirement,
    AuthoritySession,
)
from .provider import AuthorityIntervalProvider
from .registry import AuthorityProviderRegistration, AuthorityProviderRegistry

_INTERVAL_STATUSES = frozenset({"stable", "drifted", "unverifiable"})
_COMPLETION_STATUSES = frozenset({"fresh", "stale", "unverifiable"})
_EXPECTED_CHANGES = frozenset({"none", "operation"})
_UNVERIFIABLE_ACTIONS = frozenset({"fail", "record"})


def interval_decision(
    interval_status: str,
    completion_status: str,
    on_unverifiable: str,
) -> str:
    """Return the canonical runtime decision for interval evidence."""

    if interval_status not in _INTERVAL_STATUSES:
        raise ValueError("invalid authority interval status")
    if completion_status not in _COMPLETION_STATUSES:
        raise ValueError("invalid authority completion status")
    if on_unverifiable not in _UNVERIFIABLE_ACTIONS:
        raise ValueError("invalid unverifiable authority policy")
    if interval_status == "drifted" or completion_status == "stale":
        return "deny"
    if interval_status == "unverifiable" or completion_status == "unverifiable":
        return "record" if on_unverifiable == "record" else "deny"
    return "allow"


class AuthorityResolver:
    def __init__(self, registry: AuthorityProviderRegistry) -> None:
        self._registry = registry

    def enforce(
        self,
        requirement: AuthorityRequirement,
        declarations: Mapping[str, AuthorityDeclaration],
        context: AuthorityContext,
    ) -> AuthorityReceipt:
        return self.begin(requirement, declarations, context).admission

    def begin(
        self,
        requirement: AuthorityRequirement,
        declarations: Mapping[str, AuthorityDeclaration],
        context: AuthorityContext,
        *,
        policy: AuthorityObservationPolicy | None = None,
    ) -> AuthoritySession:
        if policy is not None:
            self._validate_policy(policy)
        declaration = declarations.get(requirement.logical_ref)
        if declaration is None:
            raise ValueError(
                "contract failed: missing authority binding "
                f"'{requirement.logical_ref}' for capability '{requirement.capability}'"
            )
        if declaration.capability != requirement.capability:
            raise ValueError(
                "contract failed: authority capability mismatch "
                f"('{requirement.logical_ref}' declares '{declaration.capability}', "
                f"operation requires '{requirement.capability}')"
            )

        try:
            registration = self._registry.registration(declaration.provider)
        except ValueError as exc:
            raise ValueError(f"contract failed: {exc}") from exc
        provider = registration.provider
        if requirement.capability not in registration.capabilities:
            raise ValueError(
                "contract failed: authority provider capability mismatch "
                f"('{registration.name}' does not support '{requirement.capability}')"
            )

        try:
            provider.validate_configuration(declaration, context)
            evaluation = provider.evaluate(declaration, context)
        except ValueError as exc:
            raise ValueError(
                f"contract failed: authority '{requirement.logical_ref}' "
                f"provider '{registration.name}': {exc}"
            ) from exc
        if not isinstance(evaluation, AuthorityEvaluation):
            raise ValueError(  # noqa: TRY004 - provider violations are contract failures
                f"contract failed: authority '{requirement.logical_ref}' "
                f"provider '{registration.name}' returned an invalid evaluation"
            )
        if not evaluation.healthy:
            detail = evaluation.result or "authority is not ready"
            raise ValueError(
                f"contract failed: authority '{requirement.logical_ref}' "
                f"provider '{registration.name}' is not ready "
                f"(state={evaluation.state or 'unknown'}): {detail}"
            )

        if evaluation.observation is not None:
            try:
                self._validate_observation(evaluation.observation)
            except ValueError as exc:
                raise ValueError(
                    f"contract failed: authority '{requirement.logical_ref}' "
                    f"provider '{registration.name}': {exc}"
                ) from exc

        receipt = self._receipt(requirement, registration, evaluation)
        self._validate_evidence(receipt.to_evidence(), "authority admission evidence")
        session = AuthoritySession(
            requirement=requirement,
            declaration=declaration,
            context=context,
            admission=receipt,
        )
        if policy is not None and policy.on_unverifiable == "fail":
            self._require_verifiable_interval(provider, session, policy)
        return session

    def complete(
        self,
        session: AuthoritySession,
        policy: AuthorityObservationPolicy,
        *,
        completion_floor: str,
    ) -> AuthorityIntervalReceipt:
        self._validate_policy(policy)
        registration = self._registry.registration(session.declaration.provider)
        provider = registration.provider
        before = session.admission.observation

        try:
            after_evaluation = provider.evaluate(
                session.declaration,
                session.context,
            )
        except ValueError as exc:
            return self._unavailable_receipt(
                session,
                policy,
                before=before,
                result=f"completion authority observation failed: {exc}",
            )
        except Exception:  # noqa: BLE001 - third-party provider boundary
            return self._unavailable_receipt(
                session,
                policy,
                before=before,
                result="completion authority observation failed",
            )

        if not isinstance(after_evaluation, AuthorityEvaluation):
            return self._unavailable_receipt(
                session,
                policy,
                before=before,
                result="provider returned an invalid completion authority evaluation",
            )

        after = after_evaluation.observation
        if after is not None:
            try:
                self._validate_observation(after)
            except ValueError as exc:
                return self._unavailable_receipt(
                    session,
                    policy,
                    before=before,
                    result=f"invalid completion authority observation: {exc}",
                )
        if not after_evaluation.healthy:
            detail = after_evaluation.result or "authority is not ready"
            return AuthorityIntervalReceipt(
                logical_ref=session.requirement.logical_ref,
                capability=session.requirement.capability,
                provider=registration.name,
                provider_identity=registration.identity,
                expected_change=policy.expected_change,
                on_unverifiable=policy.on_unverifiable,
                interval_status="unverifiable",
                completion_status="unverifiable",
                decision="deny",
                result=(
                    "authority was not ready at completion "
                    f"(state={after_evaluation.state or 'unknown'}): {detail}"
                ),
                detection_strength="readiness",
                freshness_basis="none",
                before=before,
                after=after,
            )

        if (
            before is None
            or after is None
            or not isinstance(provider, AuthorityIntervalProvider)
        ):
            return self._unverifiable_receipt(
                session,
                policy,
                before=before,
                after=after,
                result="provider does not expose comparable authority observations",
            )

        try:
            observed_at = self._parse_utc(after.observed_at, "observation.observed_at")
            floor = self._parse_utc(completion_floor, "completion_floor")
        except ValueError as exc:
            return self._unavailable_receipt(
                session,
                policy,
                before=before,
                result=f"invalid completion authority observation: {exc}",
            )
        if observed_at < floor:
            return AuthorityIntervalReceipt(
                logical_ref=session.requirement.logical_ref,
                capability=session.requirement.capability,
                provider=registration.name,
                provider_identity=registration.identity,
                expected_change=policy.expected_change,
                on_unverifiable=policy.on_unverifiable,
                interval_status="unverifiable",
                completion_status="stale",
                decision="deny",
                result="completion authority observation predates the completion read",
                detection_strength=after.strength,
                freshness_basis="observation time",
                before=before,
                after=after,
            )
        if before.scope != after.scope:
            return self._unverifiable_receipt(
                session,
                policy,
                before=before,
                after=after,
                result="authority observation scope changed during the operation",
            )

        try:
            evaluation = provider.evaluate_interval(
                session.declaration,
                session.context,
                before,
                after,
                policy,
                completion_floor,
            )
        except ValueError as exc:
            return self._unavailable_receipt(
                session,
                policy,
                before=before,
                after=after,
                result=f"authority interval evaluation failed: {exc}",
            )
        except Exception:  # noqa: BLE001 - third-party provider boundary
            return self._unavailable_receipt(
                session,
                policy,
                before=before,
                after=after,
                result="authority interval evaluation failed",
            )

        if not isinstance(evaluation, AuthorityIntervalEvaluation):
            return self._unavailable_receipt(
                session,
                policy,
                before=before,
                after=after,
                result="provider returned an invalid authority interval evaluation",
            )
        if evaluation.interval_status not in _INTERVAL_STATUSES:
            return self._unavailable_receipt(
                session,
                policy,
                before=before,
                after=after,
                result="provider returned an invalid authority interval status",
            )
        if evaluation.completion_status not in _COMPLETION_STATUSES:
            return self._unavailable_receipt(
                session,
                policy,
                before=before,
                after=after,
                result="provider returned an invalid authority completion status",
            )
        for field, value in (
            ("result", evaluation.result),
            ("detection strength", evaluation.detection_strength),
            ("freshness basis", evaluation.freshness_basis),
        ):
            if not str(value or "").strip():
                return self._unavailable_receipt(
                    session,
                    policy,
                    before=before,
                    after=after,
                    result=f"provider returned an empty authority interval {field}",
                )

        decision = self._decision(evaluation, policy)
        return AuthorityIntervalReceipt(
            logical_ref=session.requirement.logical_ref,
            capability=session.requirement.capability,
            provider=registration.name,
            provider_identity=registration.identity,
            expected_change=policy.expected_change,
            on_unverifiable=policy.on_unverifiable,
            interval_status=evaluation.interval_status,
            completion_status=evaluation.completion_status,
            decision=decision,
            result=evaluation.result,
            detection_strength=evaluation.detection_strength,
            freshness_basis=evaluation.freshness_basis,
            before=before,
            after=after,
        )

    @staticmethod
    def _receipt(
        requirement: AuthorityRequirement,
        registration: AuthorityProviderRegistration,
        evaluation: AuthorityEvaluation,
    ) -> AuthorityReceipt:
        return AuthorityReceipt(
            logical_ref=requirement.logical_ref,
            capability=requirement.capability,
            provider=registration.name,
            provider_identity=registration.identity,
            state=evaluation.state,
            result=evaluation.result or "admitted",
            instance=evaluation.instance,
            endpoint=evaluation.endpoint,
            revision=evaluation.revision,
            freshness=evaluation.freshness,
            observation=evaluation.observation,
        )

    @staticmethod
    def _validate_policy(policy: AuthorityObservationPolicy) -> None:
        if policy.expected_change not in _EXPECTED_CHANGES:
            raise ValueError("invalid expected authority change policy")
        if policy.on_unverifiable not in _UNVERIFIABLE_ACTIONS:
            raise ValueError("invalid unverifiable authority policy")

    @classmethod
    def _validate_observation(cls, observation: AuthorityObservation) -> None:
        if not isinstance(observation, AuthorityObservation):
            raise ValueError(  # noqa: TRY004 - provider violations are contract failures
                "provider returned an invalid authority observation"
            )
        for field, value in (
            ("token", observation.token),
            ("scope", observation.scope),
            ("strength", observation.strength),
        ):
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"authority observation {field} must be a non-empty string")
        if not isinstance(observation.observed_at, str):
            raise ValueError(  # noqa: TRY004 - provider violations are contract failures
                "authority observation time must be an ISO-8601 timestamp"
            )
        cls._parse_utc(observation.observed_at, "authority observation time")
        if not isinstance(observation.metadata, Mapping):
            raise ValueError(  # noqa: TRY004 - provider violations are contract failures
                "authority observation metadata must be an object"
            )
        cls._validate_evidence(
            observation.to_evidence(),
            "authority observation",
        )

    @staticmethod
    def _validate_evidence(evidence: Mapping[str, object], label: str) -> None:
        try:
            json.dumps(evidence, allow_nan=False)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{label} must be JSON serializable") from exc

    @staticmethod
    def _require_verifiable_interval(
        provider,
        session: AuthoritySession,
        policy: AuthorityObservationPolicy,
    ) -> None:
        before = session.admission.observation
        if before is None or not isinstance(provider, AuthorityIntervalProvider):
            raise ValueError(
                "contract failed: authority interval evidence required by policy "
                "is unavailable before dispatch"
            )
        try:
            verifiable = provider.interval_verifiable(
                session.declaration,
                session.context,
                before,
                policy,
            )
        except ValueError as exc:
            raise ValueError(
                "contract failed: authority interval capability evaluation failed: "
                f"{exc}"
            ) from exc
        except Exception as exc:
            raise ValueError(
                "contract failed: authority interval capability evaluation failed"
            ) from exc
        if not isinstance(verifiable, bool):
            raise ValueError(  # noqa: TRY004 - provider violations are contract failures
                "contract failed: authority provider returned an invalid interval capability"
            )
        if not verifiable:
            raise ValueError(
                "contract failed: authority provider cannot establish the interval "
                "evidence required by policy"
            )

    @staticmethod
    def _parse_utc(value: str, field: str) -> datetime:
        text = str(value or "").strip()
        if not text:
            raise ValueError(f"{field} is required")
        try:
            parsed = datetime.fromisoformat(text)
        except ValueError as exc:
            raise ValueError(f"{field} must be an ISO-8601 timestamp") from exc
        if parsed.tzinfo is None:
            raise ValueError(f"{field} must include a UTC offset")
        return parsed.astimezone(UTC)

    @staticmethod
    def _decision(
        evaluation: AuthorityIntervalEvaluation,
        policy: AuthorityObservationPolicy,
    ) -> str:
        return interval_decision(
            evaluation.interval_status,
            evaluation.completion_status,
            policy.on_unverifiable,
        )

    @staticmethod
    def _unavailable_receipt(
        session: AuthoritySession,
        policy: AuthorityObservationPolicy,
        *,
        before: AuthorityObservation | None,
        after: AuthorityObservation | None = None,
        result: str,
    ) -> AuthorityIntervalReceipt:
        return AuthorityIntervalReceipt(
            logical_ref=session.requirement.logical_ref,
            capability=session.requirement.capability,
            provider=session.admission.provider,
            provider_identity=session.admission.provider_identity,
            expected_change=policy.expected_change,
            on_unverifiable=policy.on_unverifiable,
            interval_status="unverifiable",
            completion_status="unverifiable",
            decision="deny",
            result=result,
            detection_strength="none",
            freshness_basis="none",
            before=before,
            after=after,
        )

    @staticmethod
    def _unverifiable_receipt(
        session: AuthoritySession,
        policy: AuthorityObservationPolicy,
        *,
        before: AuthorityObservation | None,
        after: AuthorityObservation | None,
        result: str,
    ) -> AuthorityIntervalReceipt:
        decision = "record" if policy.on_unverifiable == "record" else "deny"
        return AuthorityIntervalReceipt(
            logical_ref=session.requirement.logical_ref,
            capability=session.requirement.capability,
            provider=session.admission.provider,
            provider_identity=session.admission.provider_identity,
            expected_change=policy.expected_change,
            on_unverifiable=policy.on_unverifiable,
            interval_status="unverifiable",
            completion_status="unverifiable",
            decision=decision,
            result=result,
            detection_strength="none",
            freshness_basis="none",
            before=before,
            after=after,
        )


_DEFAULT_REGISTRY: AuthorityProviderRegistry | None = None


def default_authority_registry() -> AuthorityProviderRegistry:
    global _DEFAULT_REGISTRY
    if _DEFAULT_REGISTRY is None:
        from .providers.kubernetes import KubernetesAuthorityProvider
        from .providers.nautobot import NautobotAuthorityProvider
        from .providers.netbox import NetBoxAuthorityProvider

        registry = AuthorityProviderRegistry()
        from hyops import __version__

        from .models import AuthorityProviderIdentity

        for provider in (
            NetBoxAuthorityProvider(),
            NautobotAuthorityProvider(),
            KubernetesAuthorityProvider(),
        ):
            provider_type = type(provider)
            registry.register(
                provider,
                identity=AuthorityProviderIdentity(
                    source="builtin",
                    distribution="hybridops-core",
                    version=__version__,
                    entry_point=(
                        f"{provider_type.__module__}:{provider_type.__qualname__}"
                    ),
                ),
            )
        _DEFAULT_REGISTRY = registry
    return _DEFAULT_REGISTRY
