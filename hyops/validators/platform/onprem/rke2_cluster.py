"""hyops.validators.platform.onprem.rke2_cluster

purpose: Validate inputs for platform/onprem/rke2-cluster module.
maintainer: HybridOps.Tech
"""

from __future__ import annotations

from typing import Any

from hyops.validators.common import (
    normalize_required_env,
    require_mapping,
    require_non_empty_str,
    require_port,
)

def _require_vm_key_list(value: Any, field: str) -> list[str]:
    if not isinstance(value, list) or not value:
        raise ValueError(f"{field} must be a non-empty list")
    out: list[str] = []
    for idx, item in enumerate(value, start=1):
        out.append(require_non_empty_str(item, f"{field}[{idx}]"))
    return out


def _normalize_str_list(value: Any, field: str) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise ValueError(f"{field} must be a list when set")
    out: list[str] = []
    for idx, item in enumerate(value, start=1):
        out.append(require_non_empty_str(item, f"{field}[{idx}]"))
    return out


def validate(inputs: dict[str, Any]) -> None:
    data = require_mapping(inputs, "inputs")

    lifecycle = str(data.get("_hyops_lifecycle_command") or "").strip().lower()

    # Inventory: either explicit inventory_groups (advanced) or state-driven inventory_vm_groups.
    inventory_groups = data.get("inventory_groups")
    inventory_state_ref = data.get("inventory_state_ref")
    inventory_vm_groups = data.get("inventory_vm_groups")

    if inventory_groups is not None and not isinstance(inventory_groups, dict):
        raise ValueError("inputs.inventory_groups must be a mapping when set")

    if isinstance(inventory_groups, dict) and inventory_groups:
        servers = inventory_groups.get("rke2_servers")
        if not isinstance(servers, list) or not servers:
            raise ValueError("inputs.inventory_groups must include group 'rke2_servers' with at least one host")

        for idx, item in enumerate(servers, start=1):
            host = require_mapping(item, f"inputs.inventory_groups.rke2_servers[{idx}]")
            require_non_empty_str(host.get("name"), f"inputs.inventory_groups.rke2_servers[{idx}].name")
            require_non_empty_str(host.get("host"), f"inputs.inventory_groups.rke2_servers[{idx}].host")

        agents = inventory_groups.get("rke2_agents")
        if agents is not None:
            if not isinstance(agents, list):
                raise ValueError("inputs.inventory_groups.rke2_agents must be a list when set")
            for idx, item in enumerate(agents, start=1):
                host = require_mapping(item, f"inputs.inventory_groups.rke2_agents[{idx}]")
                require_non_empty_str(host.get("name"), f"inputs.inventory_groups.rke2_agents[{idx}].name")
                require_non_empty_str(host.get("host"), f"inputs.inventory_groups.rke2_agents[{idx}].host")
    else:
        if inventory_state_ref is None or not isinstance(inventory_state_ref, str) or not inventory_state_ref.strip():
            raise ValueError(
                "inputs.inventory_state_ref is required when inputs.inventory_groups is empty "
                "(recommended: platform/onprem/platform-vm)"
            )

        if inventory_vm_groups is None or not isinstance(inventory_vm_groups, dict) or not inventory_vm_groups:
            raise ValueError(
                "inputs.inventory_vm_groups must be a non-empty mapping when inputs.inventory_state_ref is set"
            )

        if "rke2_servers" not in inventory_vm_groups:
            raise ValueError("inputs.inventory_vm_groups must include key 'rke2_servers'")

        _require_vm_key_list(inventory_vm_groups.get("rke2_servers"), "inputs.inventory_vm_groups.rke2_servers")

        agents = inventory_vm_groups.get("rke2_agents")
        if agents is not None:
            _require_vm_key_list(agents, "inputs.inventory_vm_groups.rke2_agents")

    if data.get("inventory_requires_ipam") is not None and not isinstance(data.get("inventory_requires_ipam"), bool):
        raise ValueError("inputs.inventory_requires_ipam must be a boolean when set")

    # SSH defaults applied to every host.
    require_non_empty_str(data.get("target_user"), "inputs.target_user")
    if data.get("target_port") is not None:
        require_port(data.get("target_port"), "inputs.target_port")

    if data.get("ssh_private_key_file") is not None and str(data.get("ssh_private_key_file") or "").strip() != "":
        require_non_empty_str(data.get("ssh_private_key_file"), "inputs.ssh_private_key_file")

    if data.get("ssh_proxy_jump_host") is not None and str(data.get("ssh_proxy_jump_host") or "").strip() != "":
        require_non_empty_str(data.get("ssh_proxy_jump_host"), "inputs.ssh_proxy_jump_host")
        if data.get("ssh_proxy_jump_user") is not None:
            require_non_empty_str(data.get("ssh_proxy_jump_user"), "inputs.ssh_proxy_jump_user")
        if data.get("ssh_proxy_jump_port") is not None:
            require_port(data.get("ssh_proxy_jump_port"), "inputs.ssh_proxy_jump_port")
    if data.get("ssh_proxy_jump_auto") is not None and not isinstance(data.get("ssh_proxy_jump_auto"), bool):
        raise ValueError("inputs.ssh_proxy_jump_auto must be a boolean when set")

    if data.get("become") is not None and not isinstance(data.get("become"), bool):
        raise ValueError("inputs.become must be a boolean when set")
    if data.get("become_user") is not None:
        require_non_empty_str(data.get("become_user"), "inputs.become_user")

    if data.get("load_vault_env") is not None and not isinstance(data.get("load_vault_env"), bool):
        raise ValueError("inputs.load_vault_env must be a boolean when set")
    if data.get("rke2_image_preflight") is not None and not isinstance(data.get("rke2_image_preflight"), bool):
        raise ValueError("inputs.rke2_image_preflight must be a boolean when set")
    if data.get("rke2_image_preflight_timeout_s") is not None:
        raw_timeout = data.get("rke2_image_preflight_timeout_s")
        if isinstance(raw_timeout, bool) or not isinstance(raw_timeout, int):
            raise ValueError("inputs.rke2_image_preflight_timeout_s must be an integer")
        if raw_timeout < 30:
            raise ValueError("inputs.rke2_image_preflight_timeout_s must be >= 30")
    if data.get("rke2_auto_image_tarballs") is not None and not isinstance(data.get("rke2_auto_image_tarballs"), bool):
        raise ValueError("inputs.rke2_auto_image_tarballs must be a boolean when set")
    _normalize_str_list(data.get("rke2_image_tarball_urls"), "inputs.rke2_image_tarball_urls")
    if data.get("rke2_stage_images_from_controller") is not None and not isinstance(
        data.get("rke2_stage_images_from_controller"), bool
    ):
        raise ValueError("inputs.rke2_stage_images_from_controller must be a boolean when set")
    if data.get("rke2_image_download_timeout_s") is not None:
        raw_dl_timeout = data.get("rke2_image_download_timeout_s")
        if isinstance(raw_dl_timeout, bool) or not isinstance(raw_dl_timeout, int):
            raise ValueError("inputs.rke2_image_download_timeout_s must be an integer")
        if raw_dl_timeout < 30:
            raise ValueError("inputs.rke2_image_download_timeout_s must be >= 30")

    # Role wiring.
    if lifecycle != "destroy":
        if data.get("rke2_server_role_fqcn") is not None:
            require_non_empty_str(data.get("rke2_server_role_fqcn"), "inputs.rke2_server_role_fqcn")
        if data.get("rke2_agent_role_fqcn") is not None:
            require_non_empty_str(data.get("rke2_agent_role_fqcn"), "inputs.rke2_agent_role_fqcn")
        if data.get("rke2_manifest_role_fqcn") is not None:
            require_non_empty_str(data.get("rke2_manifest_role_fqcn"), "inputs.rke2_manifest_role_fqcn")
        # Legacy compatibility (older examples/inputs).
        if data.get("rke2_role_fqcn") is not None and str(data.get("rke2_role_fqcn") or "").strip() != "":
            require_non_empty_str(data.get("rke2_role_fqcn"), "inputs.rke2_role_fqcn")

        rke2_token_env = require_non_empty_str(data.get("rke2_token_env"), "inputs.rke2_token_env")
        required_env = normalize_required_env(data.get("required_env"), "inputs.required_env")
        if rke2_token_env not in required_env:
            raise ValueError(
                f"inputs.required_env must include: {rke2_token_env} (referenced by inputs.rke2_token_env)"
            )

    role_vars = data.get("rke2_role_vars")
    if role_vars is not None and not isinstance(role_vars, dict):
        raise ValueError("inputs.rke2_role_vars must be a mapping when set")

    kubeconfig_out = data.get("rke2_kubeconfig_out")
    if kubeconfig_out is not None and not isinstance(kubeconfig_out, str):
        raise ValueError("inputs.rke2_kubeconfig_out must be a string when set")
