"""hyops.validators.platform.network.decision_dispatcher

purpose: Validate inputs for platform/network/decision-dispatcher module.
Architecture Decision: ADR-N/A (decision dispatcher validator)
maintainer: HybridOps
"""

from __future__ import annotations

import re
from typing import Any

from hyops.validators.common import (
    require_int_ge as _require_int_ge,
    require_non_empty_str as _require_non_empty_str,
    require_port as _require_port,
)

_REF_RE = re.compile(r"^[a-z0-9][a-z0-9._/@-]*[a-z0-9]$")
_EXECUTION_PLANES = {
    "runner-local",
    "private-overlay",
    "bastion-explicit",
    "gcp-iap",
    "public-ephemeral",
    "workstation-direct",
}


def _validate_ref(value: str, field: str) -> None:
    if not _REF_RE.fullmatch(value):
        raise ValueError(f"{field} must be a canonical ref")


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


def _validate_routes(routes: dict[str, Any]) -> None:
    if not routes:
        raise ValueError("inputs.dispatcher_routes must be a non-empty mapping")

    for decision_type, route_raw in routes.items():
        route = route_raw
        _require_non_empty_str(decision_type, f"inputs.dispatcher_routes[{decision_type}]")
        if not isinstance(route, dict) or not route:
            raise ValueError(f"inputs.dispatcher_routes.{decision_type} must be a non-empty mapping")
        target_kind = _require_non_empty_str(
            route.get("target_kind"),
            f"inputs.dispatcher_routes.{decision_type}.target_kind",
        ).lower()
        if target_kind not in {"blueprint", "module"}:
            raise ValueError(
                f"inputs.dispatcher_routes.{decision_type}.target_kind must be one of: blueprint, module"
            )
        target_ref = _require_non_empty_str(
            route.get("target_ref"),
            f"inputs.dispatcher_routes.{decision_type}.target_ref",
        )
        _validate_ref(target_ref, f"inputs.dispatcher_routes.{decision_type}.target_ref")
        _require_non_empty_str(
            route.get("target_env"),
            f"inputs.dispatcher_routes.{decision_type}.target_env",
        )
        plane = _require_non_empty_str(
            route.get("execution_plane"),
            f"inputs.dispatcher_routes.{decision_type}.execution_plane",
        ).lower()
        if plane not in _EXECUTION_PLANES:
            raise ValueError(
                f"inputs.dispatcher_routes.{decision_type}.execution_plane must be one of: "
                + ", ".join(sorted(_EXECUTION_PLANES))
            )
        requires_approval = route.get("requires_approval")
        if requires_approval is not None and not isinstance(requires_approval, bool):
            raise ValueError(
                f"inputs.dispatcher_routes.{decision_type}.requires_approval must be a boolean when set"
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

    _require_non_empty_str(data.get("dispatcher_role_fqcn"), "inputs.dispatcher_role_fqcn")
    state = _require_non_empty_str(data.get("dispatcher_state"), "inputs.dispatcher_state").lower()
    if state not in {"present", "absent"}:
        raise ValueError("inputs.dispatcher_state must be 'present' or 'absent'")
    if state == "absent":
        return

    _require_non_empty_str(data.get("dispatcher_root"), "inputs.dispatcher_root")
    _require_non_empty_str(
        data.get("dispatcher_decision_records_dir"),
        "inputs.dispatcher_decision_records_dir",
    )
    mode = _require_non_empty_str(
        data.get("dispatcher_execution_mode") or "record-only",
        "inputs.dispatcher_execution_mode",
    ).lower()
    if mode != "record-only":
        raise ValueError("inputs.dispatcher_execution_mode must be 'record-only' in v1")
    require_approval = data.get("dispatcher_require_approval")
    if not isinstance(require_approval, bool):
        raise ValueError("inputs.dispatcher_require_approval must be a boolean")
    _require_int_ge(data.get("dispatcher_poll_seconds"), "inputs.dispatcher_poll_seconds", 5)
    _require_non_empty_str(data.get("dispatcher_log_level"), "inputs.dispatcher_log_level")

    routes = data.get("dispatcher_routes")
    if not isinstance(routes, dict):
        raise ValueError("inputs.dispatcher_routes must be a non-empty mapping")
    _validate_routes(routes)
