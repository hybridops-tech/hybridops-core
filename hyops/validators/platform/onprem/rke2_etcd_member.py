"""Validate inputs for platform/onprem/rke2-etcd-member."""

from __future__ import annotations

from typing import Any
from urllib.parse import urlparse

from hyops.validators.common import (
    normalize_lifecycle_command,
    require_bool,
    require_mapping,
    require_non_empty_str,
    require_port,
)


def _validate_operator_inventory(data: dict[str, Any]) -> None:
    groups = data.get("inventory_groups")
    if isinstance(groups, dict) and groups:
        members = groups.get("rke2_operator")
        if not isinstance(members, list) or len(members) != 1:
            raise ValueError("inputs.inventory_groups.rke2_operator must contain exactly one host")
        host = require_mapping(members[0], "inputs.inventory_groups.rke2_operator[1]")
        require_non_empty_str(host.get("name"), "inputs.inventory_groups.rke2_operator[1].name")
        require_non_empty_str(
            host.get("host") or host.get("ansible_host"),
            "inputs.inventory_groups.rke2_operator[1].host",
        )
        return

    state_ref = str(data.get("inventory_state_ref") or "").strip()
    if not state_ref:
        raise ValueError(
            "inputs.inventory_state_ref is required when inputs.inventory_groups is empty "
            "(recommended: platform/onprem/platform-vm)"
        )
    vm_groups = data.get("inventory_vm_groups")
    if not isinstance(vm_groups, dict):
        raise ValueError("inputs.inventory_vm_groups must be a mapping when inventory_state_ref is set")
    members = vm_groups.get("rke2_operator")
    if not isinstance(members, list) or len(members) != 1:
        raise ValueError("inputs.inventory_vm_groups.rke2_operator must contain exactly one VM key")
    require_non_empty_str(members[0], "inputs.inventory_vm_groups.rke2_operator[1]")


def _validate_peer_url(value: Any) -> None:
    raw = require_non_empty_str(value, "inputs.etcd_member_peer_url")
    parsed = urlparse(raw)
    if parsed.scheme != "https" or not parsed.hostname or parsed.port != 2380:
        raise ValueError("inputs.etcd_member_peer_url must be an https URL with explicit port 2380")
    if parsed.path not in ("", "/") or parsed.query or parsed.fragment or parsed.username or parsed.password:
        raise ValueError("inputs.etcd_member_peer_url must contain only scheme, host, and port")


def validate(inputs: dict[str, Any]) -> None:
    data = require_mapping(inputs, "inputs")
    lifecycle = normalize_lifecycle_command(data)

    _validate_operator_inventory(data)

    if data.get("inventory_requires_ipam") is not None:
        require_bool(data.get("inventory_requires_ipam"), "inputs.inventory_requires_ipam")
    if data.get("target_user") is not None:
        require_non_empty_str(data.get("target_user"), "inputs.target_user")
    if data.get("target_port") is not None:
        require_port(data.get("target_port"), "inputs.target_port")
    if str(data.get("ssh_private_key_file") or "").strip():
        require_non_empty_str(data.get("ssh_private_key_file"), "inputs.ssh_private_key_file")
    for field in ("ssh_proxy_jump_auto", "become", "connectivity_check", "load_vault_env"):
        if data.get(field) is not None:
            require_bool(data.get(field), f"inputs.{field}")
    if data.get("ssh_proxy_jump_host") is not None and str(data.get("ssh_proxy_jump_host") or "").strip():
        require_non_empty_str(data.get("ssh_proxy_jump_host"), "inputs.ssh_proxy_jump_host")
        if data.get("ssh_proxy_jump_port") is not None:
            require_port(data.get("ssh_proxy_jump_port"), "inputs.ssh_proxy_jump_port")

    if lifecycle == "destroy":
        return

    require_non_empty_str(data.get("etcd_member_name"), "inputs.etcd_member_name")
    _validate_peer_url(data.get("etcd_member_peer_url"))

    if data.get("remove_kubernetes_node") is not None:
        require_bool(data.get("remove_kubernetes_node"), "inputs.remove_kubernetes_node")
    if bool(data.get("remove_kubernetes_node", True)):
        require_non_empty_str(data.get("kubernetes_node_name"), "inputs.kubernetes_node_name")

    require_bool(data.get("member_removal_confirm"), "inputs.member_removal_confirm")
    if not bool(data.get("member_removal_confirm")):
        raise ValueError("inputs.member_removal_confirm must be true (explicit confirmation required)")
