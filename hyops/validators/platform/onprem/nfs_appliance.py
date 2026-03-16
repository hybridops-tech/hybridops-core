"""hyops.validators.platform.onprem.nfs_appliance

purpose: Validate inputs for platform/onprem/nfs-appliance.
maintainer: HybridOps.Tech
"""

from __future__ import annotations

import re
from typing import Any

from hyops.validators.registry import ModuleValidationError

from ._proxmox_vm import validate_vm_pool_inputs


def _validate_ssh_key_inputs(inputs: dict[str, Any]) -> None:
    ssh_keys_from_init = inputs.get("ssh_keys_from_init")
    if ssh_keys_from_init is not None and not isinstance(ssh_keys_from_init, bool):
        raise ModuleValidationError("inputs.ssh_keys_from_init must be a boolean")

    keys: list[str] = []

    raw_keys = inputs.get("ssh_keys")
    if raw_keys is not None:
        if not isinstance(raw_keys, list):
            raise ModuleValidationError("inputs.ssh_keys must be a list of SSH public keys when set")
        for idx, key in enumerate(raw_keys, start=1):
            if not isinstance(key, str) or not key.strip():
                raise ModuleValidationError(f"inputs.ssh_keys[{idx}] must be a non-empty SSH public key string")
            keys.append(key.strip())

    raw_single = inputs.get("ssh_public_key")
    if raw_single is not None:
        if not isinstance(raw_single, str) or not raw_single.strip():
            raise ModuleValidationError("inputs.ssh_public_key must be a non-empty string when set")
        keys.append(raw_single.strip())

    raw_init_target = inputs.get("ssh_keys_init_target")
    if raw_init_target is not None and str(raw_init_target).strip():
        init_target = str(raw_init_target).strip()
        marker = init_target.upper()
        if "CHANGE_ME" in marker or "<" in init_target or "EXAMPLE" in marker:
            raise ModuleValidationError("inputs.ssh_keys_init_target must not contain placeholder values")

    if ssh_keys_from_init and keys:
        raise ModuleValidationError(
            "inputs.ssh_keys_from_init=true cannot be combined with explicit inputs.ssh_keys or inputs.ssh_public_key. "
            "Choose one source of truth: set ssh_keys_from_init=false to use explicit keys, "
            "or remove the explicit key inputs to consume the init-discovered key."
        )

    if not ssh_keys_from_init and not keys:
        raise ModuleValidationError(
            "platform/onprem/nfs-appliance requires SSH key material. "
            "Set inputs.ssh_keys (preferred), inputs.ssh_public_key, or enable inputs.ssh_keys_from_init=true."
        )

    pubkey_re = re.compile(
        r"^(ssh-(ed25519|rsa|dss)|ecdsa-sha2-nistp(256|384|521))\s+[A-Za-z0-9+/=]+(?:\s+.+)?$"
    )
    for idx, key in enumerate(keys, start=1):
        marker = key.upper()
        if "CHANGE_ME" in marker or "<" in key or "EXAMPLE" in marker:
            raise ModuleValidationError(
                f"inputs SSH key #{idx} appears to be a placeholder. Provide a real public key."
            )
        if not pubkey_re.match(key):
            raise ModuleValidationError(
                f"inputs SSH key #{idx} is not a valid OpenSSH public key format"
            )


def _has_required_meta_data(payload: str) -> bool:
    text = str(payload or "")
    has_instance_id = re.search(r"(?im)^\s*instance-id\s*:\s*\S+", text) is not None
    has_local_hostname = re.search(r"(?im)^\s*local-hostname\s*:\s*\S+", text) is not None
    return has_instance_id and has_local_hostname


def _has_nfs_bootstrap(payload: str) -> bool:
    text = str(payload or "")
    has_server_pkg = any(token in text for token in ("nfs-kernel-server", "nfs-server"))
    has_export_path = any(token in text for token in ("/etc/exports", "/etc/exports.d/", "exportfs -ra"))
    has_cloud_config = text.lstrip().startswith("#cloud-config")
    return has_cloud_config and has_server_pkg and has_export_path


def _validate_vm_bootstrap(inputs: dict[str, Any]) -> None:
    module_payload = str(inputs.get("cloud_init_user_data") or "").strip()
    module_meta_payload = str(inputs.get("cloud_init_meta_data") or "").strip()
    vms = inputs.get("vms")
    vm_name = str(inputs.get("vm_name") or "").strip()

    if isinstance(vms, dict) and vms:
        missing_payload: list[str] = []
        missing_meta: list[str] = []
        invalid_payload: list[str] = []
        invalid_meta: list[str] = []
        for raw_name, raw_cfg in vms.items():
            logical_name = str(raw_name or "").strip() or "<unnamed>"
            payload = module_payload
            meta_payload = module_meta_payload
            if isinstance(raw_cfg, dict):
                payload = str(raw_cfg.get("cloud_init_user_data") or module_payload).strip()
                meta_payload = str(raw_cfg.get("cloud_init_meta_data") or module_meta_payload).strip()
            if not payload:
                missing_payload.append(logical_name)
                continue
            if not meta_payload:
                missing_meta.append(logical_name)
                continue
            if not _has_nfs_bootstrap(payload):
                invalid_payload.append(logical_name)
                continue
            if not _has_required_meta_data(meta_payload):
                invalid_meta.append(logical_name)
        if missing_payload:
            raise ModuleValidationError(
                "NFS appliance VMs require explicit cloud_init_user_data. Missing for: " + ", ".join(sorted(missing_payload))
            )
        if missing_meta:
            raise ModuleValidationError(
                "NFS appliance VMs require explicit cloud_init_meta_data (instance-id/local-hostname). Missing for: "
                + ", ".join(sorted(missing_meta))
            )
        if invalid_payload:
            raise ModuleValidationError(
                "NFS appliance cloud_init_user_data must look like real NFS bootstrap intent (cloud-config + NFS server package + export definition/reload) for: "
                + ", ".join(sorted(invalid_payload))
            )
        if invalid_meta:
            raise ModuleValidationError(
                "NFS appliance cloud_init_meta_data must contain instance-id and local-hostname for: "
                + ", ".join(sorted(invalid_meta))
            )
        return

    if vm_name:
        if not module_payload:
            raise ModuleValidationError(
                "inputs.cloud_init_user_data is required for platform/onprem/nfs-appliance single-VM mode"
            )
        if not module_meta_payload:
            raise ModuleValidationError(
                "inputs.cloud_init_meta_data is required for platform/onprem/nfs-appliance single-VM mode"
            )
        if not _has_nfs_bootstrap(module_payload):
            raise ModuleValidationError(
                "inputs.cloud_init_user_data must include real NFS bootstrap intent (cloud-config + NFS server package + export definition/reload)"
            )
        if not _has_required_meta_data(module_meta_payload):
            raise ModuleValidationError(
                "inputs.cloud_init_meta_data must contain instance-id and local-hostname"
            )


def validate(inputs: dict[str, Any]) -> None:
    data = inputs if isinstance(inputs, dict) else {}
    lifecycle = str(data.get("_hyops_lifecycle_command") or "").strip().lower()
    if lifecycle == "destroy":
        return

    validate_vm_pool_inputs(inputs)

    ssh_username = str(inputs.get("ssh_username") or "").strip()
    if ssh_username:
        marker = ssh_username.upper()
        if "CHANGE_ME" in marker or "<" in ssh_username or "EXAMPLE" in marker:
            raise ModuleValidationError("inputs.ssh_username must not contain placeholder values")

    _validate_ssh_key_inputs(inputs)
    _validate_vm_bootstrap(inputs)
