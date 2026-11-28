"""Observe a persisted contract and publish its validation condition."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from typing import Any, Protocol

from hyops.continuity.api import ApiCondition, ApiStatus, v1alpha1


class StatusConflict(Exception):
    """The resource changed before its status could be written."""


class StatusClient(Protocol):
    def read(self, namespace: str, name: str) -> Mapping[str, Any] | None: ...

    def replace_status(
        self,
        namespace: str,
        name: str,
        uid: str,
        resource_version: str,
        status: dict[str, Any],
    ) -> None: ...


def _utc_now() -> str:
    return datetime.now(UTC).isoformat()


def _pending_update(
    payload: Mapping[str, Any], generation: int, now: Callable[[], str]
) -> dict[str, Any] | None:
    try:
        resource = v1alpha1.decode(payload)
    except v1alpha1.ApiValidationError as error:
        if error.path != "$.spec" and not error.path.startswith("$.spec."):
            raise ValueError(
                f"Invalid persisted contract: {error.reason_code}"
            ) from None
        # Without a valid spec, previously reported recovery sets cannot be verified.
        declarations = ()
        try:
            status = v1alpha1.decode_status(payload.get("status", {}), generation)
        except v1alpha1.ApiValidationError as invalid_status:
            raise ValueError(
                f"Invalid persisted status: {invalid_status.reason_code}"
            ) from None
        state, reason = "False", error.reason_code
        message = "Contract specification is invalid."
    else:
        declarations = resource.spec.recovery_sets
        status = resource.status or ApiStatus()
        state, reason, message = "True", "Validated", "Contract specification is valid."

    if status.phase != "Pending":
        return None
    current = next((c for c in status.conditions if c.type == "ContractValid"), None)
    condition = ApiCondition(
        type="ContractValid",
        status=state,
        reason=reason,
        message=message,
        last_transition_time=(
            current.last_transition_time
            if current and current.status == state
            else now()
        ),
        observed_generation=generation,
    )
    if current == condition and status.observed_generation == generation:
        return None
    raw = payload.get("status")
    proposed = dict(raw) if raw is not None else {"phase": "Pending"}
    conditions = {item["type"]: item for item in proposed.get("conditions", [])}
    conditions[condition.type] = v1alpha1.encode_condition(condition)
    proposed.update(observedGeneration=generation, conditions=list(conditions.values()))
    v1alpha1.decode_status(proposed, generation, declarations)
    return proposed


def reconcile(
    client: StatusClient,
    namespace: str,
    name: str,
    *,
    now: Callable[[], str] = _utc_now,
) -> bool:
    """Write a changed Pending validation status, retrying from a fresh read on conflict."""

    initial_uid = None
    attempts_left = 3
    while True:
        payload = client.read(namespace, name)
        if payload is None:
            return False
        if not isinstance(payload, Mapping):
            raise ValueError("Persisted contract must be an object")
        metadata = payload.get("metadata")
        if not isinstance(metadata, Mapping) or (
            metadata.get("name") != name or metadata.get("namespace") != namespace
        ):
            raise ValueError(
                "Contract identity does not match the requested namespace and name"
            )
        uid, version = metadata.get("uid"), metadata.get("resourceVersion")
        generation = metadata.get("generation")
        if not (
            isinstance(uid, str)
            and uid.strip()
            and isinstance(version, str)
            and version.strip()
            and type(generation) is int
            and generation > 0
        ):
            raise ValueError(
                "Persisted contract requires a UID, resource version and generation"
            )
        if metadata.get("deletionTimestamp") is not None or (
            initial_uid is not None and uid != initial_uid
        ):
            return False
        initial_uid = uid
        status = _pending_update(payload, generation, now)
        if status is None:
            return False
        try:
            client.replace_status(namespace, name, uid, version, status)
        except StatusConflict:
            attempts_left -= 1
            if not attempts_left:
                raise
        else:
            return True
