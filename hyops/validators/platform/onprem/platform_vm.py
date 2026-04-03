"""
purpose: Validate inputs for platform/onprem/platform-vm module.
maintainer: HybridOps.Tech
"""

from __future__ import annotations

from typing import Any

from ._proxmox_vm import validate_vm_pool_inputs


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
    data = inputs if isinstance(inputs, dict) else {}
    lifecycle = str(data.get("_hyops_lifecycle_command") or "").strip().lower()
    if lifecycle == "destroy":
        return

    validate_vm_pool_inputs(inputs)
    _validate_post_apply_ssh_readiness(inputs)
