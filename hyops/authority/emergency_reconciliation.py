"""Authority-transition semantics for brownfield emergency reconciliation.

This module defines how the runtime handles situations where declared intent,
controller cache, and live device state disagree. It provides tools to:

1. Distinguish between fresh observations and stale controller cache
2. Make explicit provisional-use decisions
3. Track operations authorized vs forbidden for provisional observations
4. Record transitions back to declared authority
5. Handle unverifiable freshness/provenance according to policy
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from .models import (
    AuthorityObservation,
    AuthorityTransitionDecision,
    AuthorityTransitionPolicy,
    AuthorityTransitionRecord,
    ObservationSource,
)


def detect_observation_disagreement(
    declared: AuthorityObservation,
    controller_cache: AuthorityObservation | None,
    live_device: AuthorityObservation | None,
) -> bool:
    """Detect whether competing observations disagree about authority state.

    Args:
        declared: The declared/intended authority state
        controller_cache: Last known controller observation (may be stale)
        live_device: Fresh observation from the actual device (during emergency)

    Returns:
        True if any two observations disagree, False if all agree or only one exists
    """
    observations = [declared]
    if controller_cache is not None:
        observations.append(controller_cache)
    if live_device is not None:
        observations.append(live_device)

    # If only one observation exists, no disagreement
    if len(observations) <= 1:
        return False

    # Check if all observations have the same token (state)
    tokens = {obs.token for obs in observations}
    return len(tokens) > 1


def is_observation_fresh(
    observation: AuthorityObservation,
    now: str = "",
    max_age_s: int = 3600,
) -> tuple[bool, str]:
    """Determine if an observation is sufficiently fresh based on timestamp.

    Args:
        observation: The observation to evaluate
        now: ISO 8601 timestamp (uses current time if empty)
        max_age_s: Maximum acceptable age in seconds

    Returns:
        (is_fresh, reason) tuple
    """
    if not now:
        now = datetime.now(timezone.utc).isoformat()

    if not observation.observed_at:
        return False, "observation has no timestamp"

    try:
        obs_time = datetime.fromisoformat(observation.observed_at.replace("Z", "+00:00"))
        now_time = datetime.fromisoformat(now.replace("Z", "+00:00"))
        age_s = (now_time - obs_time).total_seconds()

        if age_s < 0:
            return False, f"observation timestamp is in the future ({observation.observed_at})"
        if age_s > max_age_s:
            return False, f"observation age ({age_s}s) exceeds threshold ({max_age_s}s)"
        return True, f"observation is fresh ({age_s:.1f}s old)"
    except ValueError as e:
        return False, f"cannot parse timestamp: {e}"


def distinguish_observation_sources(
    declared: AuthorityObservation,
    controller_cache: AuthorityObservation | None,
    live_device: AuthorityObservation | None,
) -> dict[str, ObservationSource]:
    """Distinguish observation sources and their provenance basis.

    Args:
        declared: The declared/intended authority state
        controller_cache: Last known controller observation (may be stale)
        live_device: Fresh observation from the actual device

    Returns:
        Dict mapping source type to ObservationSource with metadata
    """
    sources: dict[str, ObservationSource] = {}

    # Declared authority is always present and implicitly verified
    sources["declared"] = ObservationSource(
        source_type="declared",
        freshness_basis="verified",  # Declared is always "fresh" by definition
        last_known_update=declared.observed_at,
        metadata={"scope": declared.scope, "strength": declared.strength},
    )

    # Controller cache is stale if present
    if controller_cache is not None:
        is_fresh, reason = is_observation_fresh(controller_cache, max_age_s=60)  # 60s threshold for cache
        sources["controller_cache"] = ObservationSource(
            source_type="controller_cache",
            freshness_basis="inferred" if is_fresh else "unverifiable",
            last_known_update=controller_cache.observed_at,
            metadata={"freshness_reason": reason, "scope": controller_cache.scope},
        )

    # Live device observation is fresh if present
    if live_device is not None:
        is_fresh, reason = is_observation_fresh(live_device, max_age_s=30)  # 30s threshold for live
        sources["live_device"] = ObservationSource(
            source_type="live_device",
            freshness_basis="verified" if is_fresh else "unverifiable",
            last_known_update=live_device.observed_at,
            metadata={"freshness_reason": reason, "scope": live_device.scope},
        )

    return sources


def decide_provisional_use(
    declared: AuthorityObservation,
    live_device: AuthorityObservation | None,
    policy: AuthorityTransitionPolicy,
    operator_decision: bool = False,
    authorized_operations: frozenset[str] = frozenset(),
) -> AuthorityTransitionDecision | None:
    """Decide whether to use provisional live device observation during reconciliation.

    Args:
        declared: The declared/intended authority state
        live_device: Fresh observation from the actual device
        policy: Transition policy governing provisional use
        operator_decision: Whether operator explicitly authorized provisional use
        authorized_operations: Operations this provisional observation may authorize

    Returns:
        AuthorityTransitionDecision if provisional use is allowed, None otherwise
    """
    if live_device is None:
        return None

    if not policy.allow_provisional_use:
        return None

    if policy.require_explicit_decision and not operator_decision:
        return None

    decision_id = f"emergency-reconciliation-{datetime.now(timezone.utc).isoformat()}"

    return AuthorityTransitionDecision(
        decision_id=decision_id,
        timestamp=datetime.now(timezone.utc).isoformat(),
        decision_type="provisional_use",
        rationale="Using live device observation to recover from detected authority disagreement",
        authorized_by="operator" if operator_decision else "policy",
        provisional_observation=live_device,
        authorized_operations=authorized_operations,
        forbidden_operations=frozenset({"update_declared", "permanent_state_change"}),
    )


def create_transition_record(
    logical_ref: str,
    capability: str,
    provider: str,
    declared: AuthorityObservation,
    controller_cache: AuthorityObservation | None,
    live_device: AuthorityObservation | None,
    decision: AuthorityTransitionDecision | None,
) -> AuthorityTransitionRecord:
    """Create a complete authority transition record for emergency reconciliation.

    Args:
        logical_ref: Logical authority reference
        capability: Authority capability
        provider: Provider name
        declared: The declared/intended authority state
        controller_cache: Last known controller observation (may be stale)
        live_device: Fresh observation from the actual device
        decision: Provisional-use decision (if any)

    Returns:
        AuthorityTransitionRecord with all transition details
    """
    disagreement = detect_observation_disagreement(declared, controller_cache, live_device)

    # Determine transition type
    if not disagreement:
        transition_type = "no_transition"
    elif decision is None:
        transition_type = "keep_declared"
    else:
        transition_type = "provisional_use"

    return AuthorityTransitionRecord(
        logical_ref=logical_ref,
        capability=capability,
        provider=provider,
        declared_authority=declared,
        controller_cache=controller_cache,
        live_device_state=live_device,
        detected_disagreement=disagreement,
        transition_decision=decision,
        transition_type=transition_type,
    )


def record_return_to_declared(
    record: AuthorityTransitionRecord,
    return_condition_met: bool,
    result: str = "",
) -> AuthorityTransitionRecord:
    """Update transition record to show return to declared authority.

    Args:
        record: The existing transition record
        return_condition_met: Whether the return condition was satisfied
        result: Detail about the return (e.g., "declared state verified")

    Returns:
        Updated transition record with return-to-declared information
    """
    return AuthorityTransitionRecord(
        logical_ref=record.logical_ref,
        capability=record.capability,
        provider=record.provider,
        declared_authority=record.declared_authority,
        controller_cache=record.controller_cache,
        live_device_state=record.live_device_state,
        detected_disagreement=record.detected_disagreement,
        transition_decision=record.transition_decision,
        transition_type=record.transition_type,
        return_to_declared_at=datetime.now(timezone.utc).isoformat(),
        return_condition_met=return_condition_met,
        return_result=result,
    )
