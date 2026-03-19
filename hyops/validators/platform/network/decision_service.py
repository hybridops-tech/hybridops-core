"""hyops.validators.platform.network.decision_service

purpose: Validate inputs for platform/network/decision-service module.
Architecture Decision: ADR-N/A (decision service validator)
maintainer: HybridOps
"""

from __future__ import annotations

import re
from typing import Any, cast

from hyops.validators.common import (
    require_int_ge as _require_int_ge,
    require_non_empty_str as _require_non_empty_str,
    require_number_ge as _require_number_ge,
    require_port as _require_port,
)
from hyops.validators.platform.network import cloudflare_traffic_steering as cloudflare_traffic_steering_validator
from hyops.validators.platform.network import dns_routing as dns_routing_validator


_REF_RE = re.compile(r"^[a-z0-9][a-z0-9._/-]*[a-z0-9]$")


def _validate_module_ref(value: str, field: str) -> None:
    if not _REF_RE.fullmatch(value):
        raise ValueError(f"{field} must be a canonical module ref")


def _validate_state_ref(value: Any, field: str) -> None:
    token = _require_non_empty_str(value, field)
    base = token.split("#", 1)[0].strip()
    _validate_module_ref(base, field)


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
            "(recommended: org/hetzner/shared-control-host#edge_control_host)"
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


def _validate_cloudflare_traffic_steering_base_inputs(base: dict[str, Any], desired: str) -> None:
    payload: dict[str, Any] = {
        "inventory_groups": base.get("inventory_groups") if isinstance(base.get("inventory_groups"), dict) else {},
        "target_user": str(base.get("target_user") or "root"),
        "target_port": base.get("target_port", 22),
        "become": base.get("become", False),
        "required_env": base.get("required_env") if isinstance(base.get("required_env"), list) else [],
        "required_env_destroy": base.get("required_env_destroy") if isinstance(base.get("required_env_destroy"), list) else [],
        "load_vault_env": base.get("load_vault_env", False),
        "steering_state": str(base.get("steering_state") or "present"),
        "apply_mode": str(base.get("apply_mode") or "bootstrap"),
        "cloudflare_api_token_env": str(base.get("cloudflare_api_token_env") or "CLOUDFLARE_API_TOKEN"),
        "cloudflare_account_id": str(base.get("cloudflare_account_id") or ""),
        "cloudflare_account_name": str(base.get("cloudflare_account_name") or ""),
        "zone_name": base.get("zone_name"),
        "hostname": base.get("hostname"),
        "route_pattern": base.get("route_pattern"),
        "worker_name": base.get("worker_name"),
        "compatibility_date": str(base.get("compatibility_date") or "2026-03-19"),
        "ensure_dns_record": base.get("ensure_dns_record", False),
        "dns_record_type": base.get("dns_record_type"),
        "dns_record_name": base.get("dns_record_name"),
        "dns_record_target": base.get("dns_record_target"),
        "dns_record_proxied": base.get("dns_record_proxied", True),
        "desired": desired,
        "balanced_burst_weight_pct": base.get("balanced_burst_weight_pct"),
        "cookie_name": base.get("cookie_name"),
        "cookie_ttl_s": base.get("cookie_ttl_s"),
        "root_redirect_path": base.get("root_redirect_path"),
        "forward_prefixes": base.get("forward_prefixes"),
        "primary_origin_url": base.get("primary_origin_url"),
        "burst_origin_url": base.get("burst_origin_url"),
        "status_timeout_s": base.get("status_timeout_s"),
        "status_retries": base.get("status_retries"),
        "status_retry_delay_s": base.get("status_retry_delay_s"),
    }
    try:
        cloudflare_traffic_steering_validator.validate(payload)
    except Exception as exc:
        raise ValueError(
            f"inputs.actions.module_inputs invalid for platform/network/cloudflare-traffic-steering: {exc}"
        ) from exc


def _validate_module_state_guards(actions: dict[str, Any]) -> None:
    guards = actions.get("module_state_guards")
    if guards is None:
        return
    if not isinstance(guards, dict):
        raise ValueError("inputs.actions.module_state_guards must be a mapping when set")

    for action_name in ("cutover", "failback"):
        items = guards.get(action_name, [])
        if items in (None, ""):
            items = []
        if not isinstance(items, list):
            raise ValueError(f"inputs.actions.module_state_guards.{action_name} must be a list when set")
        for idx, item in enumerate(items, start=1):
            if not isinstance(item, dict):
                raise ValueError(
                    f"inputs.actions.module_state_guards.{action_name}[{idx}] must be a mapping"
                )
            _validate_state_ref(
                item.get("state_ref"),
                f"inputs.actions.module_state_guards.{action_name}[{idx}].state_ref",
            )
            require_status = item.get("require_status")
            if require_status is not None:
                _require_non_empty_str(
                    require_status,
                    f"inputs.actions.module_state_guards.{action_name}[{idx}].require_status",
                )

            outputs_equal = item.get("outputs_equal")
            if outputs_equal is not None:
                if not isinstance(outputs_equal, dict):
                    raise ValueError(
                        f"inputs.actions.module_state_guards.{action_name}[{idx}].outputs_equal must be a mapping"
                    )
                for key, value in outputs_equal.items():
                    _require_non_empty_str(
                        key,
                        f"inputs.actions.module_state_guards.{action_name}[{idx}].outputs_equal key",
                    )
                    if isinstance(value, (dict, list)):
                        raise ValueError(
                            f"inputs.actions.module_state_guards.{action_name}[{idx}].outputs_equal.{key} "
                            "must be a scalar value"
                        )

            outputs_non_empty = item.get("outputs_non_empty")
            if outputs_non_empty is not None:
                if not isinstance(outputs_non_empty, list):
                    raise ValueError(
                        f"inputs.actions.module_state_guards.{action_name}[{idx}].outputs_non_empty must be a list"
                    )
                for out_idx, key in enumerate(outputs_non_empty, start=1):
                    _require_non_empty_str(
                        key,
                        f"inputs.actions.module_state_guards.{action_name}[{idx}].outputs_non_empty[{out_idx}]",
                    )


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
    desired_by_module = {
        "platform/network/dns-routing": {"primary", "secondary"},
        "platform/network/cloudflare-traffic-steering": {"primary", "balanced", "burst"},
    }
    cutover_allowed = desired_by_module.get(cutover_ref, {"primary", "secondary"})
    failback_allowed = desired_by_module.get(failback_ref, {"primary", "secondary"})
    if cutover_desired not in cutover_allowed:
        raise ValueError(
            "inputs.actions.cutover_desired must be one of: " + ", ".join(sorted(cutover_allowed))
        )
    if failback_desired not in failback_allowed:
        raise ValueError(
            "inputs.actions.failback_desired must be one of: " + ", ".join(sorted(failback_allowed))
        )

    dry_run = data.get("dry_run")
    if not isinstance(dry_run, bool):
        raise ValueError("inputs.dry_run must be a boolean")
    enable_actions = data.get("decision_enable_actions")
    if not isinstance(enable_actions, bool):
        raise ValueError("inputs.decision_enable_actions must be a boolean")
    execution_mode = _require_non_empty_str(
        data.get("decision_execution_mode") or "emit-only",
        "inputs.decision_execution_mode",
    ).lower()
    if execution_mode not in {"emit-only", "local-hyops"}:
        raise ValueError("inputs.decision_execution_mode must be one of: emit-only, local-hyops")
    if execution_mode == "emit-only" and enable_actions:
        raise ValueError(
            "inputs.decision_enable_actions must be false when inputs.decision_execution_mode=emit-only"
        )
    if execution_mode == "local-hyops" and not dry_run and not enable_actions:
        raise ValueError(
            "inputs.decision_enable_actions must be true when "
            "inputs.decision_execution_mode=local-hyops and inputs.dry_run=false"
        )

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
    runtime_root = data.get("decision_runtime_root")
    if runtime_root is not None and str(runtime_root).strip():
        _require_non_empty_str(runtime_root, "inputs.decision_runtime_root")
    action_env_names = data.get("decision_action_env_names", [])
    if action_env_names not in (None, ""):
        if not isinstance(action_env_names, list):
            raise ValueError("inputs.decision_action_env_names must be a list when set")
        for idx, item in enumerate(action_env_names, start=1):
            token = _require_non_empty_str(item, f"inputs.decision_action_env_names[{idx}]")
            if "REPLACE_" in token.upper():
                raise ValueError(f"inputs.decision_action_env_names[{idx}] contains placeholder token")
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

    require_action_state_guards = data.get("decision_require_action_state_guards")
    if not isinstance(require_action_state_guards, bool):
        raise ValueError("inputs.decision_require_action_state_guards must be a boolean")

    _validate_module_state_guards(actions)

    if execution_mode == "local-hyops" and enable_actions and not dry_run:
        base_inputs = actions.get("module_inputs")
        if not isinstance(base_inputs, dict) or not base_inputs:
            raise ValueError(
                "inputs.actions.module_inputs must be a non-empty mapping when decision actions are enabled"
            )
        if cutover_ref == "platform/network/dns-routing":
            _validate_dns_routing_base_inputs({**base_inputs, "desired": cutover_desired})
        if failback_ref == "platform/network/dns-routing":
            _validate_dns_routing_base_inputs({**base_inputs, "desired": failback_desired})
        if cutover_ref == "platform/network/cloudflare-traffic-steering":
            _validate_cloudflare_traffic_steering_base_inputs(base_inputs, cutover_desired)
        if failback_ref == "platform/network/cloudflare-traffic-steering":
            _validate_cloudflare_traffic_steering_base_inputs(base_inputs, failback_desired)

    if require_action_state_guards:
        guards = actions.get("module_state_guards")
        if not isinstance(guards, dict):
            raise ValueError(
                "inputs.actions.module_state_guards must be configured when decision_require_action_state_guards=true"
            )
