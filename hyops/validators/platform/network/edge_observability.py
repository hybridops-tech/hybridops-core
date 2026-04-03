"""hyops.validators.platform.network.edge_observability

purpose: Validate inputs for platform/network/edge-observability module.
maintainer: HybridOps.Tech
"""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import urlparse

from hyops.validators.common import normalize_required_env, require_non_empty_str, require_port


_HOSTPORT_RE = re.compile(r"^[A-Za-z0-9_.-]+:[0-9]{1,5}$")


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
        token = require_non_empty_str(item, f"{field}[{idx}]")
        if not _HOSTPORT_RE.fullmatch(token):
            raise ValueError(f"{field}[{idx}] must match host:port")
        port = int(token.rsplit(":", 1)[1])
        if port < 1 or port > 65535:
            raise ValueError(f"{field}[{idx}] has invalid port")


def _validate_probe_targets(value: Any, field: str, *, required: bool) -> None:
    if value is None:
        if required:
            raise ValueError(f"{field} must be a non-empty list")
        return
    if not isinstance(value, list):
        raise ValueError(f"{field} must be a list")
    if required and not value:
        raise ValueError(f"{field} must be a non-empty list")
    for idx, item in enumerate(value, start=1):
        if not isinstance(item, dict):
            raise ValueError(f"{field}[{idx}] must be a mapping")
        require_non_empty_str(item.get("name"), f"{field}[{idx}].name")
        token = require_non_empty_str(item.get("url"), f"{field}[{idx}].url")
        parsed = urlparse(token)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError(f"{field}[{idx}].url must be a valid http(s) URL")


def _validate_string_mapping(value: Any, field: str) -> None:
    if value is None:
        return
    if not isinstance(value, dict):
        raise ValueError(f"{field} must be a mapping")
    for key, item in value.items():
        require_non_empty_str(key, f"{field}.key")
        require_non_empty_str(item, f"{field}.{key}")


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
            require_non_empty_str(item.get("name"), f"inputs.inventory_groups.edge[{idx}].name")
            require_non_empty_str(
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
        require_non_empty_str(item, f"inputs.inventory_vm_groups.edge[{idx}]")


def validate(inputs: dict[str, Any]) -> None:
    data = inputs or {}
    if not isinstance(data, dict):
        raise ValueError("inputs must be a mapping")

    _validate_inventory(data)

    require_non_empty_str(data.get("target_user"), "inputs.target_user")
    if data.get("target_port") is not None:
        require_port(data.get("target_port"), "inputs.target_port")

    if data.get("become") is not None and not isinstance(data.get("become"), bool):
        raise ValueError("inputs.become must be a boolean when set")
    if data.get("become_user") is not None:
        require_non_empty_str(data.get("become_user"), "inputs.become_user")

    require_non_empty_str(data.get("edge_obs_role_fqcn"), "inputs.edge_obs_role_fqcn")

    state = require_non_empty_str(data.get("edge_obs_state"), "inputs.edge_obs_state").lower()
    if state not in {"present", "absent"}:
        raise ValueError("inputs.edge_obs_state must be 'present' or 'absent'")
    if state == "absent":
        return

    required_env = normalize_required_env(data.get("required_env"), "inputs.required_env")

    for key in (
        "edge_obs_objstore_config_env",
        "edge_obs_grafana_admin_password_env",
        "edge_obs_thanos_image",
        "edge_obs_grafana_image",
        "edge_obs_alertmanager_image",
        "edge_obs_prometheus_image",
        "edge_obs_blackbox_exporter_image",
    ):
        token = require_non_empty_str(data.get(key), f"inputs.{key}")
        if _is_placeholder(token):
            raise ValueError(f"inputs.{key} contains placeholder token")

    for key in (
        "edge_obs_enable_receive",
        "edge_obs_enable_query",
        "edge_obs_enable_store_gateway",
        "edge_obs_enable_grafana",
        "edge_obs_enable_alertmanager",
        "edge_obs_enable_ruler",
        "edge_obs_enable_prometheus",
        "edge_obs_enable_blackbox_exporter",
        "edge_obs_enable_thanos_sidecar",
        "edge_obs_enable_decision_service_scrape",
        "edge_obs_enable_burst_dashboard",
        "edge_obs_enable_public_proxy",
    ):
        if not isinstance(data.get(key), bool):
            raise ValueError(f"inputs.{key} must be a boolean")

    for key in (
        "edge_obs_receive_remote_write_port",
        "edge_obs_query_http_port",
        "edge_obs_grafana_http_port",
        "edge_obs_alertmanager_http_port",
        "edge_obs_prometheus_http_port",
        "edge_obs_blackbox_exporter_http_port",
        "edge_obs_decision_service_metrics_port",
        "edge_obs_public_http_port",
        "edge_obs_public_https_port",
    ):
        require_port(data.get(key), f"inputs.{key}")

    require_non_empty_str(data.get("edge_obs_grafana_admin_user"), "inputs.edge_obs_grafana_admin_user")
    require_non_empty_str(data.get("edge_obs_grafana_datasource_url"), "inputs.edge_obs_grafana_datasource_url")
    require_non_empty_str(data.get("edge_obs_decision_service_metrics_host"), "inputs.edge_obs_decision_service_metrics_host")
    require_non_empty_str(data.get("edge_obs_burst_dashboard_title"), "inputs.edge_obs_burst_dashboard_title")
    require_non_empty_str(data.get("edge_obs_prometheus_retention_time"), "inputs.edge_obs_prometheus_retention_time")
    require_non_empty_str(data.get("edge_obs_prometheus_scrape_interval"), "inputs.edge_obs_prometheus_scrape_interval")
    if data.get("edge_obs_public_proxy_image") is not None:
        require_non_empty_str(data.get("edge_obs_public_proxy_image"), "inputs.edge_obs_public_proxy_image")
    if data.get("edge_obs_public_contact_email") is not None:
        contact = str(data.get("edge_obs_public_contact_email") or "").strip()
        if contact and "@" not in contact:
            raise ValueError("inputs.edge_obs_public_contact_email must look like an email address when set")

    public_grafana_host = str(data.get("edge_obs_public_grafana_host") or "").strip()
    public_thanos_host = str(data.get("edge_obs_public_thanos_host") or "").strip()

    if bool(data.get("edge_obs_enable_blackbox_exporter")) and not bool(data.get("edge_obs_enable_prometheus")):
        raise ValueError("inputs.edge_obs_enable_blackbox_exporter requires inputs.edge_obs_enable_prometheus=true")
    if bool(data.get("edge_obs_enable_thanos_sidecar")) and not bool(data.get("edge_obs_enable_prometheus")):
        raise ValueError("inputs.edge_obs_enable_thanos_sidecar requires inputs.edge_obs_enable_prometheus=true")
    if bool(data.get("edge_obs_enable_decision_service_scrape")) and not bool(data.get("edge_obs_enable_prometheus")):
        raise ValueError("inputs.edge_obs_enable_decision_service_scrape requires inputs.edge_obs_enable_prometheus=true")
    if bool(data.get("edge_obs_enable_burst_dashboard")) and not bool(data.get("edge_obs_enable_grafana")):
        raise ValueError("inputs.edge_obs_enable_burst_dashboard requires inputs.edge_obs_enable_grafana=true")
    if bool(data.get("edge_obs_enable_public_proxy")):
        if not public_grafana_host and not public_thanos_host:
            raise ValueError("inputs.edge_obs_enable_public_proxy requires inputs.edge_obs_public_grafana_host and/or inputs.edge_obs_public_thanos_host")
        if public_grafana_host and not bool(data.get("edge_obs_enable_grafana")):
            raise ValueError("inputs.edge_obs_public_grafana_host requires inputs.edge_obs_enable_grafana=true")
        if public_thanos_host and not bool(data.get("edge_obs_enable_query")):
            raise ValueError("inputs.edge_obs_public_thanos_host requires inputs.edge_obs_enable_query=true")
    elif public_grafana_host or public_thanos_host:
        raise ValueError("set inputs.edge_obs_enable_public_proxy=true before configuring public Grafana or Thanos hosts")

    hashring_required = bool(data.get("edge_obs_enable_receive"))
    _validate_hostport_list(data.get("edge_obs_hashring_endpoints"), "inputs.edge_obs_hashring_endpoints", required=hashring_required)
    _validate_hostport_list(data.get("edge_obs_query_upstreams"), "inputs.edge_obs_query_upstreams", required=False)
    _validate_string_mapping(
        data.get("edge_obs_prometheus_external_labels"),
        "inputs.edge_obs_prometheus_external_labels",
    )
    _validate_probe_targets(
        data.get("edge_obs_probe_targets"),
        "inputs.edge_obs_probe_targets",
        required=bool(data.get("edge_obs_enable_prometheus")) or bool(data.get("edge_obs_enable_blackbox_exporter")) or bool(data.get("edge_obs_enable_thanos_sidecar")),
    )

    objstore_needed = bool(data.get("edge_obs_enable_receive")) or bool(data.get("edge_obs_enable_store_gateway")) or bool(data.get("edge_obs_enable_ruler"))
    if objstore_needed:
        direct_objstore = str(data.get("edge_obs_objstore_config") or "").strip()
        objstore_env = require_non_empty_str(data.get("edge_obs_objstore_config_env"), "inputs.edge_obs_objstore_config_env")
        if not direct_objstore and objstore_env not in required_env:
            raise ValueError(
                f"inputs.required_env must include {objstore_env} when inputs.edge_obs_objstore_config is empty"
            )
        if direct_objstore and _is_placeholder(direct_objstore):
            raise ValueError("inputs.edge_obs_objstore_config contains placeholder token")

    if bool(data.get("edge_obs_enable_grafana")):
        direct_pw = str(data.get("edge_obs_grafana_admin_password") or "").strip()
        pw_env = require_non_empty_str(
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
