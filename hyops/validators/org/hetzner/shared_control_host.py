"""
purpose: Validate inputs for module org/hetzner/shared-control-host.
Architecture Decision: ADR-0206 (module execution contract v1)
maintainer: HybridOps.Tech
"""

from __future__ import annotations

import ipaddress
import re
from typing import Any

from hyops.validators.common import (
    check_no_placeholder,
    opt_str,
    require_non_empty_str,
)
from hyops.validators.registry import ModuleValidationError


_SSH_PUBKEY_RE = re.compile(
    r"^(ssh-ed25519|ssh-rsa|ecdsa-sha2-nistp256|ecdsa-sha2-nistp384|ecdsa-sha2-nistp521|ssh-dss|"
    r"sk-ssh-ed25519@openssh\.com|sk-ecdsa-sha2-nistp256@openssh\.com|"
    r"sk-ssh-ed25519|sk-ecdsa-sha2-nistp256|sk-ecdsa-sha2-nistp384|sk-ecdsa-sha2-nistp521)\s+"
    r"([A-Za-z0-9+/=]+)(?:\s+.+)?$"
)
_HOST_KEY_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,62}$")


def _req_str(inputs: dict[str, Any], key: str) -> str:
    return check_no_placeholder(
        require_non_empty_str(inputs.get(key), f"inputs.{key}"),
        f"inputs.{key}",
    )


def _opt_str(inputs: dict[str, Any], key: str) -> str:
    v = opt_str(inputs.get(key), f"inputs.{key}")
    return check_no_placeholder(v, f"inputs.{key}") if v else v


def _opt_map(inputs: dict[str, Any], key: str) -> dict[str, Any]:
    v = inputs.get(key)
    if v is None:
        return {}
    if not isinstance(v, dict):
        raise ModuleValidationError(f"inputs.{key} must be a mapping when set")
    return v


def _req_cidr_list(inputs: dict[str, Any], key: str) -> list[str]:
    v = inputs.get(key)
    if not isinstance(v, list) or not v:
        raise ModuleValidationError(f"inputs.{key} must be a non-empty list")
    out: list[str] = []
    for idx, item in enumerate(v, start=1):
        if not isinstance(item, str) or not item.strip():
            raise ModuleValidationError(f"inputs.{key}[{idx}] must be a non-empty string")
        token = item.strip()
        try:
            ipaddress.ip_network(token, strict=False)
        except Exception as exc:
            raise ModuleValidationError(f"inputs.{key}[{idx}] must be a valid CIDR") from exc
        out.append(token)
    return out


def _validate_ssh_keys(inputs: dict[str, Any]) -> None:
    ssh_keys_from_init = inputs.get("ssh_keys_from_init")
    if ssh_keys_from_init is not None and not isinstance(ssh_keys_from_init, bool):
        raise ModuleValidationError("inputs.ssh_keys_from_init must be a boolean")

    raw_keys = inputs.get("ssh_keys")
    if not isinstance(raw_keys, list):
        raise ModuleValidationError("inputs.ssh_keys must be a list")
    keys = [str(item or "").strip() for item in raw_keys if str(item or "").strip()]

    if ssh_keys_from_init and keys:
        raise ModuleValidationError(
            "inputs.ssh_keys_from_init=true cannot be combined with explicit inputs.ssh_keys. "
            "Choose one source of truth: set ssh_keys_from_init=false to use explicit keys, "
            "or remove ssh_keys to consume the init-discovered key."
        )
    if not ssh_keys_from_init and not keys:
        raise ModuleValidationError(
            "inputs.ssh_keys must contain at least one public key unless inputs.ssh_keys_from_init=true"
        )

    for idx, key in enumerate(keys, start=1):
        m = _SSH_PUBKEY_RE.fullmatch(key)
        if not m:
            raise ModuleValidationError(
                f"inputs.ssh_keys[{idx}] must be a valid SSH public key "
                "(e.g. starts with ssh-ed25519/ssh-rsa/ecdsa-...)"
            )
        if len(m.group(2)) < 32:
            raise ModuleValidationError(f"inputs.ssh_keys[{idx}] appears truncated; provide a full public key")


def validate(inputs: dict[str, Any]) -> None:
    foundation_state_ref = str(inputs.get("foundation_state_ref") or "").strip()
    if foundation_state_ref:
        _req_str(inputs, "foundation_state_ref")

    private_network_id = str(inputs.get("private_network_id") or "").strip()
    if not foundation_state_ref and not private_network_id:
        raise ModuleValidationError(
            "inputs.private_network_id is required when inputs.foundation_state_ref is not set"
        )
    if private_network_id:
        _req_str(inputs, "private_network_id")

    private_network_cidr = str(inputs.get("private_network_cidr") or "").strip()
    if private_network_cidr:
        try:
            net = ipaddress.ip_network(private_network_cidr, strict=False)
        except Exception as exc:
            raise ModuleValidationError("inputs.private_network_cidr must be a valid CIDR when set") from exc
        if not isinstance(net, ipaddress.IPv4Network):
            raise ModuleValidationError("inputs.private_network_cidr must be an IPv4 CIDR")

    _req_str(inputs, "location")
    _req_str(inputs, "server_type")
    _req_str(inputs, "image")
    host_name = _req_str(inputs, "host_name")
    if not _HOST_KEY_RE.fullmatch(host_name):
        raise ModuleValidationError("inputs.host_name must match ^[a-z0-9][a-z0-9-]{0,62}$")

    _req_str(inputs, "ssh_username")
    _validate_ssh_keys(inputs)
    _req_str(inputs, "firewall_name")
    _req_cidr_list(inputs, "ssh_source_cidrs")

    private_ip = _req_str(inputs, "private_ip")
    try:
        ip = ipaddress.ip_address(private_ip)
    except Exception as exc:
        raise ModuleValidationError("inputs.private_ip must be a valid IPv4 address") from exc
    if not isinstance(ip, ipaddress.IPv4Address):
        raise ModuleValidationError("inputs.private_ip must be an IPv4 address")
    if private_network_cidr and ip not in ipaddress.ip_network(private_network_cidr, strict=False):
        raise ModuleValidationError("inputs.private_ip must be within inputs.private_network_cidr")

    for key in ("public_ipv4_enabled", "public_ipv6_enabled", "firewall_enabled"):
        value = inputs.get(key)
        if value is not None and not isinstance(value, bool):
            raise ModuleValidationError(f"inputs.{key} must be a boolean")

    labels = _opt_map(inputs, "labels")
    for k, v in labels.items():
        if not isinstance(k, str) or not k.strip():
            raise ModuleValidationError("inputs.labels keys must be non-empty strings")
        if not isinstance(v, str):
            raise ModuleValidationError(f"inputs.labels[{k!r}] must be a string")
