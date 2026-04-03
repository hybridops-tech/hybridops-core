"""
purpose: Validate inputs for platform/linux/ops-runner module.
maintainer: HybridOps.Tech
"""

from __future__ import annotations

import os
from typing import Any

from hyops.validators.common import (
    require_bool as _require_bool,
    require_mapping as _require_mapping,
    require_non_empty_str as _require_non_empty_str,
    require_str_list as _require_str_list,
)


def _require_absolute_or_empty(value: Any, field: str) -> str:
    token = str(value or "").strip()
    if not token:
        return ""
    if not token.startswith("/"):
        raise ValueError(f"{field} must be an absolute path when set")
    return token


def validate(inputs: dict[str, Any]) -> None:
    data = _require_mapping(inputs, "inputs")

    inventory_groups = data.get("inventory_groups")
    inventory_state_ref = str(data.get("inventory_state_ref") or "").strip()
    if isinstance(inventory_groups, dict) and inventory_groups:
        group = inventory_groups.get("runner")
        if not isinstance(group, list) or not group:
            raise ValueError("inputs.inventory_groups must include group 'runner' with at least one host")
    else:
        if not inventory_state_ref:
            raise ValueError(
                "inputs.inventory_state_ref is required when inputs.inventory_groups is empty "
                "(expected a runner VM-producing state)"
            )
        inventory_vm_groups = data.get("inventory_vm_groups")
        if not isinstance(inventory_vm_groups, dict) or not inventory_vm_groups:
            raise ValueError(
                "inputs.inventory_vm_groups must be a non-empty mapping when inputs.inventory_state_ref is set"
            )
        runner_group = inventory_vm_groups.get("runner")
        if not isinstance(runner_group, list) or not runner_group:
            raise ValueError("inputs.inventory_vm_groups must include non-empty group 'runner'")

    _require_non_empty_str(data.get("target_user"), "inputs.target_user")
    ssh_access_mode = str(data.get("ssh_access_mode") or "direct").strip().lower() or "direct"
    if ssh_access_mode not in {"direct", "bastion-explicit", "gcp-iap"}:
        raise ValueError("inputs.ssh_access_mode must be one of: direct, bastion-explicit, gcp-iap")
    target_port = data.get("target_port")
    if target_port is not None and (
        isinstance(target_port, bool)
        or not isinstance(target_port, int)
        or target_port <= 0
    ):
        raise ValueError("inputs.target_port must be a positive integer")
    if data.get("ssh_private_key_file") is not None and str(data.get("ssh_private_key_file") or "").strip() != "":
        _require_non_empty_str(data.get("ssh_private_key_file"), "inputs.ssh_private_key_file")

    for field in (
        "ssh_proxy_jump_auto",
        "become",
        "runner_system_link",
        "runner_force_reinstall",
        "runner_setup_base",
        "runner_setup_ansible",
        "runner_setup_cloud_gcp",
        "runner_setup_cloud_azure",
    ):
        if data.get(field) is not None:
            _require_bool(data.get(field), f"inputs.{field}")
    if ssh_access_mode == "bastion-explicit":
        _require_non_empty_str(data.get("ssh_proxy_jump_host"), "inputs.ssh_proxy_jump_host")
    if ssh_access_mode == "gcp-iap":
        if data.get("gcp_iap_instance") is not None and str(data.get("gcp_iap_instance") or "").strip() != "":
            _require_non_empty_str(data.get("gcp_iap_instance"), "inputs.gcp_iap_instance")
        if data.get("gcp_iap_project_id") is not None and str(data.get("gcp_iap_project_id") or "").strip() != "":
            _require_non_empty_str(data.get("gcp_iap_project_id"), "inputs.gcp_iap_project_id")
        if data.get("gcp_iap_zone") is not None and str(data.get("gcp_iap_zone") or "").strip() != "":
            _require_non_empty_str(data.get("gcp_iap_zone"), "inputs.gcp_iap_zone")
        if isinstance(inventory_groups, dict) and inventory_groups:
            runner_hosts = inventory_groups.get("runner")
            if isinstance(runner_hosts, list):
                for idx, item in enumerate(runner_hosts, start=1):
                    if not isinstance(item, dict):
                        continue
                    if not str(item.get("gcp_iap_instance") or "").strip():
                        continue
                    raw_tags = item.get("tags")
                    if not isinstance(raw_tags, list):
                        continue
                    tags = {str(tag).strip() for tag in raw_tags if str(tag).strip()}
                    if "allow-iap-ssh" not in tags:
                        raise ValueError(
                            "inputs.ssh_access_mode=gcp-iap requires the target VM/network policy to allow "
                            "IAP SSH. The resolved runner host "
                            f"inputs.inventory_groups['runner'][{idx}] does not publish tag 'allow-iap-ssh'. "
                            "Recreate the runner VM with that tag, or provide an equivalent firewall policy."
                        )

    release_root = _require_absolute_or_empty(data.get("runner_release_root"), "inputs.runner_release_root")
    archive_url = str(data.get("runner_release_archive_url") or "").strip()
    archive_sha256 = str(data.get("runner_release_archive_sha256") or "").strip()
    if archive_url:
        if not (archive_url.startswith("https://") or archive_url.startswith("http://") or archive_url.startswith("gs://") or archive_url.startswith("s3://")):
            raise ValueError(
                "inputs.runner_release_archive_url must start with https://, http://, gs://, or s3://"
            )
    if archive_sha256 and not archive_sha256.startswith("sha256:"):
        raise ValueError("inputs.runner_release_archive_sha256 must use format sha256:<hex>")

    if release_root and archive_url:
        raise ValueError(
            "inputs.runner_release_root and inputs.runner_release_archive_url are mutually exclusive. "
            "Choose a local unpacked release root or a versioned archive URL."
        )
    if not release_root and not archive_url and not str(os.environ.get("HYOPS_CORE_ROOT") or "").strip():
        raise ValueError(
            "inputs.runner_release_root and inputs.runner_release_archive_url are both empty and HYOPS_CORE_ROOT is not set. "
            "Provide a local unpacked HybridOps release root, a versioned archive URL, or execute via the installed hyops wrapper."
        )

    _require_absolute_or_empty(data.get("runner_stage_root"), "inputs.runner_stage_root")
    _require_absolute_or_empty(data.get("runner_install_prefix"), "inputs.runner_install_prefix")
    _require_absolute_or_empty(data.get("runner_bin_dir"), "inputs.runner_bin_dir")

    runner_state = _require_non_empty_str(data.get("runner_state"), "inputs.runner_state").lower()
    if runner_state not in {"present", "absent"}:
        raise ValueError("inputs.runner_state must be one of: present, absent")

    excludes = _require_str_list(data.get("runner_archive_excludes"), "inputs.runner_archive_excludes")
    if not excludes:
        raise ValueError("inputs.runner_archive_excludes must contain at least one entry")
