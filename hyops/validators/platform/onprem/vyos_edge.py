"""hyops.validators.platform.onprem.vyos_edge

purpose: Validate inputs for platform/onprem/vyos-edge.
maintainer: HybridOps.Tech
"""

from __future__ import annotations

import re
from typing import Any

from hyops.validators.registry import ModuleValidationError

from ._proxmox_vm import validate_vm_pool_inputs


def _has_vyos_user_data(payload: str) -> bool:
    text = str(payload or "")
    return "vyos_config_commands" in text or "runcmd" in text


def _has_supported_network_data(payload: str) -> bool:
    text = str(payload or "")
    if not text.strip():
        return False
    has_version1 = re.search(r"(?im)^\s*version\s*:\s*['\"]?1['\"]?\s*$", text) is not None
    has_config = re.search(r"(?im)^\s*config\s*:\s*$", text) is not None
    return has_version1 and has_config


def _has_required_meta_data(payload: str) -> bool:
    text = str(payload or "")
    has_instance_id = re.search(r"(?im)^\s*instance-id\s*:\s*\S+", text) is not None
    has_local_hostname = re.search(r"(?im)^\s*local-hostname\s*:\s*\S+", text) is not None
    return has_instance_id and has_local_hostname


def _has_eth1_static_override(payload: str) -> bool:
    text = str(payload or "").lower()
    for line in text.splitlines():
        normalized = line.strip()
        if "set interfaces ethernet eth1 address" not in normalized:
            continue
        if "'dhcp'" in normalized or "\"dhcp\"" in normalized or normalized.endswith(" dhcp"):
            continue
        return True
    return False


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
            "platform/onprem/vyos-edge requires SSH key material. "
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


def _primary_nic_is_static(interfaces: Any) -> bool:
    if not isinstance(interfaces, list) or not interfaces:
        return False
    nic0 = interfaces[0]
    if not isinstance(nic0, dict):
        return False
    ipv4 = nic0.get("ipv4")
    if not isinstance(ipv4, dict):
        return False
    address = str(ipv4.get("address") or "").strip().lower()
    return bool(address) and address != "dhcp"


def _require_vyos_user_data(inputs: dict[str, Any]) -> None:
    module_payload = str(inputs.get("cloud_init_user_data") or "").strip()
    module_network_payload = str(inputs.get("cloud_init_network_data") or "").strip()
    module_meta_payload = str(inputs.get("cloud_init_meta_data") or "").strip()
    module_interfaces = inputs.get("interfaces")
    vms = inputs.get("vms")
    vm_name = str(inputs.get("vm_name") or "").strip()

    if isinstance(vms, dict) and vms:
        missing: list[str] = []
        missing_meta: list[str] = []
        invalid: list[str] = []
        invalid_eth_iface: list[str] = []
        invalid_network: list[str] = []
        invalid_meta: list[str] = []
        for raw_name, raw_cfg in vms.items():
            logical_name = str(raw_name or "").strip()
            payload = ""
            network_payload = module_network_payload
            meta_payload = module_meta_payload
            interfaces = module_interfaces
            if isinstance(raw_cfg, dict):
                payload = str(raw_cfg.get("cloud_init_user_data") or module_payload).strip()
                network_payload = str(raw_cfg.get("cloud_init_network_data") or module_network_payload).strip()
                meta_payload = str(raw_cfg.get("cloud_init_meta_data") or module_meta_payload).strip()
                interfaces = raw_cfg.get("interfaces", module_interfaces)
            if not payload:
                missing.append(logical_name or "<unnamed>")
                continue
            if not meta_payload:
                missing_meta.append(logical_name or "<unnamed>")
                continue
            if not _has_vyos_user_data(payload):
                invalid.append(logical_name or "<unnamed>")
                continue
            if network_payload and not _has_supported_network_data(network_payload):
                invalid_network.append(logical_name or "<unnamed>")
                continue
            if not _has_required_meta_data(meta_payload):
                invalid_meta.append(logical_name or "<unnamed>")
                continue
            if _primary_nic_is_static(interfaces) and _has_eth1_static_override(payload):
                invalid_eth_iface.append(logical_name or "<unnamed>")
        if missing:
            raise ModuleValidationError(
                "VyOS edge VMs require explicit cloud_init_user_data. Missing for: " + ", ".join(sorted(missing))
            )
        if missing_meta:
            raise ModuleValidationError(
                "VyOS edge VMs require explicit cloud_init_meta_data (instance-id/local-hostname). Missing for: "
                + ", ".join(sorted(missing_meta))
            )
        if invalid:
            raise ModuleValidationError(
                "VyOS edge cloud_init_user_data must include vyos_config_commands or runcmd for: "
                + ", ".join(sorted(invalid))
            )
        if invalid_network:
            raise ModuleValidationError(
                "VyOS edge cloud_init_network_data must be cloud-init v1 format (version: 1 + config:) when provided, for: "
                + ", ".join(sorted(invalid_network))
            )
        if invalid_meta:
            raise ModuleValidationError(
                "VyOS edge cloud_init_meta_data must contain instance-id and local-hostname for: "
                + ", ".join(sorted(invalid_meta))
            )
        if invalid_eth_iface:
            raise ModuleValidationError(
                "VyOS edge cloud_init_user_data sets static address on eth1 while interfaces[0] is static. "
                "Use eth0 for the primary static interface. Affected VMs: " + ", ".join(sorted(invalid_eth_iface))
            )
        return

    if vm_name:
        if not module_payload:
            raise ModuleValidationError(
                "inputs.cloud_init_user_data is required for platform/onprem/vyos-edge single-VM mode"
            )
        if not module_meta_payload:
            raise ModuleValidationError(
                "inputs.cloud_init_meta_data is required for platform/onprem/vyos-edge single-VM mode"
            )
        if not _has_vyos_user_data(module_payload):
            raise ModuleValidationError(
                "inputs.cloud_init_user_data must include vyos_config_commands or runcmd for platform/onprem/vyos-edge"
            )
        if module_network_payload and not _has_supported_network_data(module_network_payload):
            raise ModuleValidationError(
                "inputs.cloud_init_network_data must be cloud-init v1 format (version: 1 + config:) when provided"
            )
        if not _has_required_meta_data(module_meta_payload):
            raise ModuleValidationError(
                "inputs.cloud_init_meta_data must contain instance-id and local-hostname"
            )
        if _primary_nic_is_static(module_interfaces) and _has_eth1_static_override(module_payload):
            raise ModuleValidationError(
                "inputs.cloud_init_user_data sets static address on eth1 while interfaces[0] is static. "
                "Use eth0 for the primary static interface."
            )


def validate(inputs: dict[str, Any]) -> None:
    validate_vm_pool_inputs(inputs)

    require_ipam = inputs.get("require_ipam")
    if require_ipam is not None and not isinstance(require_ipam, bool):
        raise ModuleValidationError("inputs.require_ipam must be a boolean when set")

    ssh_username = str(inputs.get("ssh_username") or "").strip()
    if ssh_username and ssh_username.lower() != "vyos":
        raise ModuleValidationError("inputs.ssh_username must be 'vyos' for platform/onprem/vyos-edge")

    _validate_ssh_key_inputs(inputs)
    _require_vyos_user_data(inputs)
