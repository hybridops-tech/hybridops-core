"""Validate inputs for platform/linux/containerlab-healthcheck module."""

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
        'containerlab_healthcheck_expected_version',
        'containerlab_healthcheck_labdir_base',
        'containerlab_healthcheck_pull_missing_images',
        'containerlab_healthcheck_require_deployed_lab',
        'containerlab_healthcheck_require_kvm',
        'containerlab_healthcheck_required_images',
        'containerlab_healthcheck_role_fqcn',
        'containerlab_healthcheck_topology_path',
        'gcp_iap_instance',
        'gcp_iap_project_id',
        'gcp_iap_zone',
        'inventory_groups',
        'inventory_state_ref',
        'inventory_vm_groups',
        'load_vault_env',
        'local_execution',
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