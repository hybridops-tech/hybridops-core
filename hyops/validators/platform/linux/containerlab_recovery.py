"""Validate inputs for platform/linux/containerlab-recovery module."""

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
        'containerlab_recovery_action',
        'containerlab_recovery_additional_paths',
        'containerlab_recovery_archive_path',
        'containerlab_recovery_controller_dir',
        'containerlab_recovery_disable_version_check',
        'containerlab_recovery_expected_sha256',
        'containerlab_recovery_image_refs',
        'containerlab_recovery_include_lab_dir',
        'containerlab_recovery_lab_dir',
        'containerlab_recovery_labdir_base',
        'containerlab_recovery_latest_path',
        'containerlab_recovery_mode',
        'containerlab_recovery_overwrite',
        'containerlab_recovery_path',
        'containerlab_recovery_role_fqcn',
        'containerlab_recovery_save_configs',
        'containerlab_recovery_save_configs_required',
        'containerlab_recovery_snapshot_node_filter',
        'containerlab_recovery_snapshot_timeout',
        'containerlab_recovery_source_root',
        'containerlab_recovery_topology_path',
        'containerlab_recovery_topology_relpath',
        'execution_timeout_s',
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