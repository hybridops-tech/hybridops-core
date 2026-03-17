"""hyops.validators.platform.network.edge_observability

purpose: Validate inputs for platform/network/edge-observability module.
Architecture Decision: ADR-N/A (edge observability validator)
maintainer: HybridOps.Tech
"""

from __future__ import annotations

import re
from typing import Any


_HOSTPORT_RE = re.compile(r"^[A-Za-z0-9_.-]+:[0-9]{1,5}$")


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


def _normalize_required_env(value: Any, field: str) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise ValueError(f"{field} must be a list when set")
    out: list[str] = []
    for idx, item in enumerate(value, start=1):
        out.append(_require_non_empty_str(item, f"{field}[{idx}]"))
    return out


def _is_placeholder(value: str) -> bool:
    return "REPLACE_" in value.upper()


def _validate_hostport_list(value: Any, field: str, *, required: bool) -> None:
    if value is None:
        if required:
            raise ValueError(f"{field} must be a non-empty list")
        return
    if not isinstance(value, list):
        raise ValueError(f"{field} must be a list")
    if required and not value:
        raise ValueError(f"{field} must be a non-empty list")
    for idx, item in enumerate(value, start=1):
        token = _require_non_empty_str(item, f"{field}[{idx}]")
        if not _HOSTPORT_RE.fullmatch(token):
            raise ValueError(f"{field}[{idx}] must match host:port")
        port = int(token.rsplit(":", 1)[1])
        if port < 1 or port > 65535:
            raise ValueError(f"{field}[{idx}] has invalid port")


def _validate_inventory(data: dict[str, Any]) -> None:
    inventory_groups = data.get("inventory_groups")
    inventory_state_ref = data.get("inventory_state_ref")
    inventory_vm_groups = data.get("inventory_vm_groups")

    if isinstance(inventory_groups, dict) and inventory_groups:
        group = inventory_groups.get("edge")
        if not isinstance(group, list) or not group:
            raise ValueError("inputs.inventory_groups must include group 'edge' with at least one host")
        for idx, item in enumerate(group, start=1):
            if not isinstance(item, dict):
                raise ValueError(f"inputs.inventory_groups.edge[{idx}] must be a mapping")
            _require_non_empty_str(item.get("name"), f"inputs.inventory_groups.edge[{idx}].name")
            _require_non_empty_str(
                item.get("host") or item.get("ansible_host"),
                f"inputs.inventory_groups.edge[{idx}].host",
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
    edge = inventory_vm_groups.get("edge")
    if not isinstance(edge, list) or not edge:
        raise ValueError("inputs.inventory_vm_groups must include key 'edge' with at least one VM key")
    for idx, item in enumerate(edge, start=1):
        _require_non_empty_str(item, f"inputs.inventory_vm_groups.edge[{idx}]")


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

    _require_non_empty_str(data.get("edge_obs_role_fqcn"), "inputs.edge_obs_role_fqcn")

    state = _require_non_empty_str(data.get("edge_obs_state"), "inputs.edge_obs_state").lower()
    if state not in {"present", "absent"}:
        raise ValueError("inputs.edge_obs_state must be 'present' or 'absent'")
    if state == "absent":
        return

    required_env = _normalize_required_env(data.get("required_env"), "inputs.required_env")

    for key in (
        "edge_obs_objstore_config_env",
        "edge_obs_grafana_admin_password_env",
        "edge_obs_thanos_image",
        "edge_obs_grafana_image",
        "edge_obs_alertmanager_image",
    ):
        token = _require_non_empty_str(data.get(key), f"inputs.{key}")
        if _is_placeholder(token):
            raise ValueError(f"inputs.{key} contains placeholder token")

    for key in (
        "edge_obs_enable_receive",
        "edge_obs_enable_query",
        "edge_obs_enable_store_gateway",
        "edge_obs_enable_grafana",
        "edge_obs_enable_alertmanager",
        "edge_obs_enable_ruler",
    ):
        if not isinstance(data.get(key), bool):
            raise ValueError(f"inputs.{key} must be a boolean")

    for key in (
        "edge_obs_receive_remote_write_port",
        "edge_obs_query_http_port",
        "edge_obs_grafana_http_port",
        "edge_obs_alertmanager_http_port",
    ):
        _require_port(data.get(key), f"inputs.{key}")

    _require_non_empty_str(data.get("edge_obs_grafana_admin_user"), "inputs.edge_obs_grafana_admin_user")
    _require_non_empty_str(data.get("edge_obs_grafana_datasource_url"), "inputs.edge_obs_grafana_datasource_url")

    hashring_required = bool(data.get("edge_obs_enable_receive"))
    _validate_hostport_list(data.get("edge_obs_hashring_endpoints"), "inputs.edge_obs_hashring_endpoints", required=hashring_required)
    _validate_hostport_list(data.get("edge_obs_query_upstreams"), "inputs.edge_obs_query_upstreams", required=False)

    objstore_needed = bool(data.get("edge_obs_enable_receive")) or bool(data.get("edge_obs_enable_store_gateway")) or bool(data.get("edge_obs_enable_ruler"))
    if objstore_needed:
        direct_objstore = str(data.get("edge_obs_objstore_config") or "").strip()
        objstore_env = _require_non_empty_str(data.get("edge_obs_objstore_config_env"), "inputs.edge_obs_objstore_config_env")
        if not direct_objstore and objstore_env not in required_env:
            raise ValueError(
                f"inputs.required_env must include {objstore_env} when inputs.edge_obs_objstore_config is empty"
            )
        if direct_objstore and _is_placeholder(direct_objstore):
            raise ValueError("inputs.edge_obs_objstore_config contains placeholder token")

    if bool(data.get("edge_obs_enable_grafana")):
        direct_pw = str(data.get("edge_obs_grafana_admin_password") or "").strip()
        pw_env = _require_non_empty_str(
            data.get("edge_obs_grafana_admin_password_env"),
            "inputs.edge_obs_grafana_admin_password_env",
        )
        if not direct_pw and pw_env not in required_env:
            raise ValueError(
                f"inputs.required_env must include {pw_env} when inputs.edge_obs_grafana_admin_password is empty"
            )
        if direct_pw and _is_placeholder(direct_pw):
            raise ValueError("inputs.edge_obs_grafana_admin_password contains placeholder token")

    alert_cfg = data.get("edge_obs_alertmanager_config")
    if alert_cfg is not None:
        if not isinstance(alert_cfg, (str, dict)):
            raise ValueError("inputs.edge_obs_alertmanager_config must be a string or mapping when set")
        if isinstance(alert_cfg, str) and _is_placeholder(alert_cfg):
            raise ValueError("inputs.edge_obs_alertmanager_config contains placeholder token")
