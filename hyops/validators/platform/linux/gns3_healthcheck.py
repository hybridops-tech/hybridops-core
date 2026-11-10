"""Validate inputs for platform/linux/gns3-healthcheck module."""

from __future__ import annotations

from typing import Any

from hyops.validators.registry import ModuleValidationError


def validate(inputs: dict[str, Any]) -> None:
    allowed = {
        '_hyops_invocation_command',
        '_hyops_lifecycle_command',
        'become',
        'become_user',
        'connectivity_check',
        'connectivity_timeout_s',
        'connectivity_wait_s',
        'gcp_iap_instance',
        'gcp_iap_project_id',
        'gcp_iap_zone',
        'gns3_healthcheck_deep',
        'gns3_healthcheck_password_env',
        'gns3_healthcheck_port',
        'gns3_healthcheck_require_kvm',
        'gns3_healthcheck_require_local_compute',
        'gns3_healthcheck_role_fqcn',
        'gns3_healthcheck_username',
        'inventory_groups',
        'inventory_state_ref',
        'inventory_vm_groups',
        'load_vault_env',
        'required_env',
        'required_env_destroy',
        'ssh_access_mode',
        'ssh_private_key_file',
        'ssh_proxy_jump_auto',
        'ssh_proxy_jump_host',
        'ssh_proxy_jump_port',
        'ssh_proxy_jump_user',
        'target_host',
        'target_port',
        'target_state_ref',
        'target_user',
        'target_vm_key'
    }
    unknown = sorted(str(key) for key in inputs if str(key) not in allowed)
    if unknown:
        raise ModuleValidationError(f"unknown inputs: {", ".join(unknown)}")