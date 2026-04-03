"""
purpose: Validate inputs for platform/gcp/platform-vm module.
maintainer: HybridOps.Tech
"""

from __future__ import annotations

import re
from typing import Any

from hyops.validators.common import (
    require_bool as _require_bool,
    require_mapping as _require_mapping,
    require_non_empty_str as _require_non_empty_str,
    require_positive_int as _require_positive_int,
    require_str_list as _require_str_list,
)


_VM_KEY_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,62}$")


def _reject_placeholder(value: str, field: str) -> None:
    marker = value.strip().upper()
    if marker.startswith("CHANGE_ME") or "CHANGE_ME_" in marker:
        raise ValueError(f"{field} must not contain placeholder values (found {value!r})")


def _post_apply_readiness_requires_iap(tags: list[str], vm_cfg: dict[str, Any], readiness: Any) -> bool:
    if readiness is None:
        return False
    if isinstance(readiness, bool):
        enabled = readiness
        readiness_cfg: dict[str, Any] = {}
    elif isinstance(readiness, dict):
        enabled = bool(readiness.get("enabled", True))
        readiness_cfg = readiness
    else:
        return False
    if not enabled:
        return False

    if str(readiness_cfg.get("ssh_proxy_jump_host") or "").strip():
        return False

    effective_public_ip = vm_cfg.get("assign_public_ip")
    if effective_public_ip is None:
        effective_public_ip = False
    if bool(effective_public_ip):
        return False

    effective_tags = list(tags)
    raw_vm_tags = vm_cfg.get("tags")
    if isinstance(raw_vm_tags, list):
        effective_tags.extend(str(item).strip() for item in raw_vm_tags if str(item).strip())
    return "allow-iap-ssh" not in {item.strip() for item in effective_tags if isinstance(item, str)}


def _validate_post_apply_ssh_readiness(inputs: dict[str, Any]) -> None:
    raw = inputs.get("post_apply_ssh_readiness")
    if raw is None:
        return
    if isinstance(raw, bool):
        return
    if not isinstance(raw, dict):
        raise ValueError("inputs.post_apply_ssh_readiness must be a boolean or mapping when set")

    bool_fields = ("enabled", "required", "ssh_proxy_jump_auto")
    for field in bool_fields:
        if raw.get(field) is None:
            continue
        if not isinstance(raw.get(field), bool):
            raise ValueError(f"inputs.post_apply_ssh_readiness.{field} must be a boolean when set")

    int_fields = (
        "target_port",
        "connectivity_timeout_s",
        "connectivity_wait_s",
        "ssh_proxy_jump_port",
    )
    for field in int_fields:
        if raw.get(field) is None:
            continue
        value = raw.get(field)
        if isinstance(value, bool) or not isinstance(value, int):
            raise ValueError(f"inputs.post_apply_ssh_readiness.{field} must be an integer when set")
        if field == "connectivity_wait_s":
            if value < 0:
                raise ValueError("inputs.post_apply_ssh_readiness.connectivity_wait_s must be >= 0")
        else:
            if value < 1:
                raise ValueError(f"inputs.post_apply_ssh_readiness.{field} must be >= 1")

    str_fields = ("target_user", "ssh_proxy_jump_host", "ssh_proxy_jump_user", "ssh_private_key_file")
    for field in str_fields:
        if raw.get(field) is None:
            continue
        if not isinstance(raw.get(field), str):
            raise ValueError(f"inputs.post_apply_ssh_readiness.{field} must be a string when set")


def validate(inputs: dict[str, Any]) -> None:
    data = _require_mapping(inputs, "inputs")

    project_state_ref = data.get("project_state_ref")
    if project_state_ref is not None and str(project_state_ref).strip() != "":
        project_state_ref_value = _require_non_empty_str(project_state_ref, "inputs.project_state_ref")
        _reject_placeholder(project_state_ref_value, "inputs.project_state_ref")

    project_id = data.get("project_id")
    if project_id is not None and str(project_id).strip() != "":
        project_value = _require_non_empty_str(project_id, "inputs.project_id")
        _reject_placeholder(project_value, "inputs.project_id")

    network_state_ref = data.get("network_state_ref")
    has_network_state_ref = network_state_ref is not None and str(network_state_ref).strip() != ""
    if has_network_state_ref:
        network_state_ref_value = _require_non_empty_str(network_state_ref, "inputs.network_state_ref")
        _reject_placeholder(network_state_ref_value, "inputs.network_state_ref")

    zone = _require_non_empty_str(data.get("zone"), "inputs.zone")
    _reject_placeholder(zone, "inputs.zone")
    if not has_network_state_ref:
        network = _require_non_empty_str(data.get("network"), "inputs.network")
        _reject_placeholder(network, "inputs.network")
    elif data.get("network") is not None and str(data.get("network") or "").strip() != "":
        network = _require_non_empty_str(data.get("network"), "inputs.network")
        _reject_placeholder(network, "inputs.network")
    # subnetwork is optional
    if data.get("subnetwork") is not None and str(data.get("subnetwork") or "").strip() != "":
        subnetwork = _require_non_empty_str(data.get("subnetwork"), "inputs.subnetwork")
        _reject_placeholder(subnetwork, "inputs.subnetwork")
    if data.get("subnetwork_output_key") is not None and str(data.get("subnetwork_output_key") or "").strip() != "":
        subnetwork_output_key = _require_non_empty_str(
            data.get("subnetwork_output_key"), "inputs.subnetwork_output_key"
        )
        _reject_placeholder(subnetwork_output_key, "inputs.subnetwork_output_key")

    _require_non_empty_str(data.get("machine_type"), "inputs.machine_type")
    _require_positive_int(data.get("boot_disk_size_gb"), "inputs.boot_disk_size_gb")
    _require_non_empty_str(data.get("boot_disk_type"), "inputs.boot_disk_type")
    _require_non_empty_str(data.get("source_image_project"), "inputs.source_image_project")
    _require_non_empty_str(data.get("source_image_family"), "inputs.source_image_family")
    if data.get("assign_public_ip") is not None:
        _require_bool(data.get("assign_public_ip"), "inputs.assign_public_ip")
    if data.get("enable_nested_virtualization") is not None:
        _require_bool(data.get("enable_nested_virtualization"), "inputs.enable_nested_virtualization")

    _require_non_empty_str(data.get("ssh_username"), "inputs.ssh_username")
    ssh_keys_from_init = bool(data.get("ssh_keys_from_init") is True)
    if data.get("ssh_keys_from_init") is not None and not isinstance(data.get("ssh_keys_from_init"), bool):
        raise ValueError("inputs.ssh_keys_from_init must be a boolean")
    if data.get("ssh_keys_init_target") is not None and str(data.get("ssh_keys_init_target") or "").strip() != "":
        ssh_keys_init_target = _require_non_empty_str(data.get("ssh_keys_init_target"), "inputs.ssh_keys_init_target")
        _reject_placeholder(ssh_keys_init_target, "inputs.ssh_keys_init_target")
    ssh_keys = _require_str_list(data.get("ssh_keys"), "inputs.ssh_keys")
    if ssh_keys_from_init and ssh_keys:
        raise ValueError(
            "inputs.ssh_keys_from_init=true cannot be combined with explicit inputs.ssh_keys. "
            "Choose one source of truth: set ssh_keys_from_init=false to use explicit keys, "
            "or remove ssh_keys to consume the init-discovered key."
        )
    if not ssh_keys and not ssh_keys_from_init:
        raise ValueError("inputs.ssh_keys must contain at least one public key unless inputs.ssh_keys_from_init=true")
    for idx, key in enumerate(ssh_keys, start=1):
        _reject_placeholder(key, f"inputs.ssh_keys[{idx}]")

    _validate_post_apply_ssh_readiness(data)

    tags = _require_str_list(data.get("tags"), "inputs.tags")
    if not tags:
        raise ValueError("inputs.tags must contain at least one tag")

    raw_vms = data.get("vms")
    if not isinstance(raw_vms, dict) or not raw_vms:
        raise ValueError("inputs.vms must be a non-empty mapping")

    for raw_key, raw_cfg in raw_vms.items():
        key = _require_non_empty_str(raw_key, "inputs.vms.<vm_key>").lower()
        if not _VM_KEY_RE.fullmatch(key):
            raise ValueError("inputs.vms keys must match ^[a-z0-9][a-z0-9-]{0,62}$")

        cfg = _require_mapping(raw_cfg, f"inputs.vms[{key}]")
        if _post_apply_readiness_requires_iap(tags, cfg, data.get("post_apply_ssh_readiness")):
            raise ValueError(
                f"inputs.vms[{key}] uses post_apply_ssh_readiness on a private VM without the allow-iap-ssh tag. "
                "Add allow-iap-ssh to inputs.tags or the VM-specific tags, or configure an explicit SSH proxy jump."
            )
        role = cfg.get("role")
        if role is not None and str(role).strip() != "":
            _require_non_empty_str(role, f"inputs.vms[{key}].role")

        if cfg.get("machine_type") is not None and str(cfg.get("machine_type") or "").strip() != "":
            _require_non_empty_str(cfg.get("machine_type"), f"inputs.vms[{key}].machine_type")
        if cfg.get("zone") is not None and str(cfg.get("zone") or "").strip() != "":
            _require_non_empty_str(cfg.get("zone"), f"inputs.vms[{key}].zone")
        if cfg.get("boot_disk_size_gb") is not None:
            _require_positive_int(cfg.get("boot_disk_size_gb"), f"inputs.vms[{key}].boot_disk_size_gb")
        if cfg.get("assign_public_ip") is not None:
            _require_bool(cfg.get("assign_public_ip"), f"inputs.vms[{key}].assign_public_ip")
        if cfg.get("enable_nested_virtualization") is not None:
            _require_bool(
                cfg.get("enable_nested_virtualization"),
                f"inputs.vms[{key}].enable_nested_virtualization",
            )
