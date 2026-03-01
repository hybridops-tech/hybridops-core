"""hyops.validators.platform.network.decision_service

purpose: Validate inputs for platform/network/decision-service module.
Architecture Decision: ADR-N/A (decision service validator)
maintainer: HybridOps.Studio
"""

from __future__ import annotations

import re
from typing import Any, cast

from hyops.validators.platform.network import dns_routing as dns_routing_validator


_REF_RE = re.compile(r"^[a-z0-9][a-z0-9._/-]*[a-z0-9]$")

def _require_non_empty_str(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be a non-empty string")
    return value.strip()


def _require_port(value: Any, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{field} must be an integer")
    if value < 1 or value > 65535:
        raise ValueError(f"{field} must be between 1 and 65535")
    return value


def _require_int_ge(value: Any, field: str, minimum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{field} must be an integer")
    if value < minimum:
        raise ValueError(f"{field} must be >= {minimum}")
    return value


def _require_number_ge(value: Any, field: str, minimum: float) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{field} must be a number")
    token = float(value)
    if token < minimum:
        raise ValueError(f"{field} must be >= {minimum}")
    return token


def _validate_module_ref(value: str, field: str) -> None:
    if not _REF_RE.fullmatch(value):
        raise ValueError(f"{field} must be a canonical module ref")


def _validate_inventory(data: dict[str, Any]) -> None:
    inventory_groups = data.get("inventory_groups")
    inventory_state_ref = data.get("inventory_state_ref")
    inventory_vm_groups = data.get("inventory_vm_groups")

    if isinstance(inventory_groups, dict) and inventory_groups:
        group = inventory_groups.get("edge_control")
        if not isinstance(group, list) or not group:
            raise ValueError("inputs.inventory_groups must include group 'edge_control' with at least one host")
        for idx, item in enumerate(group, start=1):
            if not isinstance(item, dict):
                raise ValueError(f"inputs.inventory_groups.edge_control[{idx}] must be a mapping")
            _require_non_empty_str(item.get("name"), f"inputs.inventory_groups.edge_control[{idx}].name")
            _require_non_empty_str(
                item.get("host") or item.get("ansible_host"),
                f"inputs.inventory_groups.edge_control[{idx}].host",
            )
        return

    if not isinstance(inventory_state_ref, str) or not inventory_state_ref.strip():
        raise ValueError(
            "inputs.inventory_state_ref is required when inputs.inventory_groups is empty "
            "(recommended: org/hetzner/wan-edge-foundation)"
        )
    if not isinstance(inventory_vm_groups, dict) or not inventory_vm_groups:
        raise ValueError(
            "inputs.inventory_vm_groups must be a non-empty mapping when inputs.inventory_state_ref is set"
        )
    group = inventory_vm_groups.get("edge_control")
    if not isinstance(group, list) or not group:
        raise ValueError("inputs.inventory_vm_groups must include key 'edge_control' with at least one VM key")
    for idx, item in enumerate(group, start=1):
        _require_non_empty_str(item, f"inputs.inventory_vm_groups.edge_control[{idx}]")


def _validate_policy(policy: dict[str, Any]) -> None:
    if not policy:
        raise ValueError("inputs.policy must be a non-empty mapping")

    signals = policy.get("signals")
    if signals is None:
        signals = {}
    if not isinstance(signals, dict):
        raise ValueError("inputs.policy.signals must be a mapping when set")

    thresholds = policy.get("thresholds")
    if not isinstance(thresholds, dict) or not thresholds:
        raise ValueError("inputs.policy.thresholds must be a non-empty mapping")

    threshold_contract = {
        "primary_up_min": "primary_up_query",
        "error_rate_ratio": "error_rate_query",
        "edge_reachability_min": "edge_reachability_query",
        "primary_latency_p95_ms": "primary_latency_p95_query",
    }

    seen_supported = False
    for key, query_key in threshold_contract.items():
        if key not in thresholds:
            continue
        seen_supported = True
        _require_number_ge(thresholds.get(key), f"inputs.policy.thresholds.{key}", 0.0)
        query = _require_non_empty_str(
            signals.get(query_key), f"inputs.policy.signals.{query_key}"
        )
        if "REPLACE_" in query.upper():
            raise ValueError(f"inputs.policy.signals.{query_key} contains placeholder token")

    if not seen_supported:
        supported = ", ".join(sorted(threshold_contract.keys()))
        raise ValueError(
            "inputs.policy.thresholds must include at least one supported key: " + supported
        )


def _validate_dns_routing_base_inputs(base: dict[str, Any]) -> None:
    # Reuse the canonical dns-routing validator so decision-service actions fail fast
    # against the same contract used by direct dns-routing runs.
    payload: dict[str, Any] = {
        "inventory_groups": base.get("inventory_groups") if isinstance(base.get("inventory_groups"), dict) else {},
        "inventory_state_ref": str(base.get("inventory_state_ref") or "").strip(),
        "inventory_vm_groups": base.get("inventory_vm_groups") if isinstance(base.get("inventory_vm_groups"), dict) else {},
        "target_user": str(base.get("target_user") or "root"),
        "target_port": base.get("target_port", 22),
        "become": base.get("become", True),
        "become_user": str(base.get("become_user") or "root"),
        "dns_role_fqcn": str(base.get("dns_role_fqcn") or "hybridops.common.dns_routing"),
        "dns_state": str(base.get("dns_state") or "present"),
        "provider": base.get("provider"),
        "zone": base.get("zone"),
        "record_fqdn": base.get("record_fqdn"),
        "record_type": base.get("record_type"),
        "ttl": base.get("ttl"),
        "desired": str(base.get("desired") or "primary"),
        "primary_targets": base.get("primary_targets"),
        "secondary_targets": base.get("secondary_targets"),
        "dry_run": base.get("dry_run", True),
        "dns_apply": base.get("dns_apply", False),
        "provider_command": base.get("provider_command", ""),
    }
    try:
        dns_routing_validator.validate(payload)
    except ValueError as exc:
        raise ValueError(f"inputs.actions.module_inputs invalid for platform/network/dns-routing: {exc}") from exc


def validate(inputs: dict[str, Any]) -> None:
    data = inputs or {}
    if not isinstance(data, dict):
        raise ValueError("inputs must be a mapping")

    _validate_inventory(data)

    _require_non_empty_str(data.get("target_user"), "inputs.target_user")
    if data.get("target_port") is not None:
        _require_port(data.get("target_port"), "inputs.target_port")
    if data.get("become") is not None and not isinstance(data.get("become"), bool):
        raise ValueError("inputs.become must be a boolean when set")
    if data.get("become_user") is not None:
        _require_non_empty_str(data.get("become_user"), "inputs.become_user")

    _require_non_empty_str(data.get("decision_role_fqcn"), "inputs.decision_role_fqcn")

    state = _require_non_empty_str(data.get("decision_state"), "inputs.decision_state").lower()
    if state not in {"present", "absent"}:
        raise ValueError("inputs.decision_state must be 'present' or 'absent'")
    if state == "absent":
        return

    thanos_query_url = _require_non_empty_str(data.get("thanos_query_url"), "inputs.thanos_query_url")
    if not (thanos_query_url.startswith("http://") or thanos_query_url.startswith("https://")):
        raise ValueError("inputs.thanos_query_url must be an http(s) URL")
    if "REPLACE_" in thanos_query_url:
        raise ValueError("inputs.thanos_query_url contains placeholder token")

    policy_raw = data.get("policy")
    if not isinstance(policy_raw, dict):
        raise ValueError("inputs.policy must be a non-empty mapping")
    _validate_policy(cast(dict[str, Any], policy_raw))

    actions = data.get("actions")
    if not isinstance(actions, dict):
        raise ValueError("inputs.actions must be a mapping")
    cutover_ref = _require_non_empty_str(actions.get("cutover_module_ref"), "inputs.actions.cutover_module_ref")
    failback_ref = _require_non_empty_str(actions.get("failback_module_ref"), "inputs.actions.failback_module_ref")
    _validate_module_ref(cutover_ref, "inputs.actions.cutover_module_ref")
    _validate_module_ref(failback_ref, "inputs.actions.failback_module_ref")

    cutover_desired = str(actions.get("cutover_desired") or "secondary").strip().lower()
    failback_desired = str(actions.get("failback_desired") or "primary").strip().lower()
    if cutover_desired not in {"primary", "secondary"}:
        raise ValueError("inputs.actions.cutover_desired must be one of: primary, secondary")
    if failback_desired not in {"primary", "secondary"}:
        raise ValueError("inputs.actions.failback_desired must be one of: primary, secondary")

    dry_run = data.get("dry_run")
    if not isinstance(dry_run, bool):
        raise ValueError("inputs.dry_run must be a boolean")
    enable_actions = data.get("decision_enable_actions")
    if not isinstance(enable_actions, bool):
        raise ValueError("inputs.decision_enable_actions must be a boolean")
    if not dry_run and not enable_actions:
        raise ValueError("inputs.decision_enable_actions must be true when inputs.dry_run=false")

    tick = _require_int_ge(data.get("tick_seconds"), "inputs.tick_seconds", 5)
    confirm = _require_int_ge(data.get("confirm_for_seconds"), "inputs.confirm_for_seconds", 0)
    stable = _require_int_ge(data.get("stable_for_seconds"), "inputs.stable_for_seconds", 0)
    cooldown = _require_int_ge(data.get("cooldown_seconds"), "inputs.cooldown_seconds", 0)

    if confirm > cooldown:
        raise ValueError("inputs.confirm_for_seconds must be <= inputs.cooldown_seconds")
    if tick > cooldown and cooldown > 0:
        raise ValueError("inputs.tick_seconds should be <= inputs.cooldown_seconds")
    if stable > 0 and stable < confirm:
        raise ValueError("inputs.stable_for_seconds must be >= inputs.confirm_for_seconds when set")

    _require_non_empty_str(data.get("decision_log_level"), "inputs.decision_log_level")
    _require_non_empty_str(data.get("decision_hyops_bin"), "inputs.decision_hyops_bin")
    _require_non_empty_str(data.get("decision_runtime_env"), "inputs.decision_runtime_env")
    _require_int_ge(data.get("decision_action_timeout_s"), "inputs.decision_action_timeout_s", 30)
    _require_int_ge(data.get("decision_signal_query_timeout_s"), "inputs.decision_signal_query_timeout_s", 1)

    require_signal_readiness = data.get("decision_require_signal_readiness")
    if not isinstance(require_signal_readiness, bool):
        raise ValueError("inputs.decision_require_signal_readiness must be a boolean")

    require_fresh_signals = data.get("decision_require_fresh_signals")
    if not isinstance(require_fresh_signals, bool):
        raise ValueError("inputs.decision_require_fresh_signals must be a boolean")

    _require_int_ge(data.get("decision_max_signal_age_s"), "inputs.decision_max_signal_age_s", 5)
    _require_int_ge(data.get("decision_min_ready_checks"), "inputs.decision_min_ready_checks", 1)

    if enable_actions and not dry_run:
        base_inputs = actions.get("module_inputs")
        if not isinstance(base_inputs, dict) or not base_inputs:
            raise ValueError(
                "inputs.actions.module_inputs must be a non-empty mapping when decision actions are enabled"
            )
        if "platform/network/dns-routing" in {cutover_ref, failback_ref}:
            _validate_dns_routing_base_inputs(base_inputs)
