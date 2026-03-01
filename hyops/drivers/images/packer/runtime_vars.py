"""Runtime variable mapping for the Packer image driver."""

from __future__ import annotations

from typing import Any

from hyops.runtime.coerce import as_port, as_positive_int


def map_runtime_vars(
    inputs: dict[str, Any],
    proxmox_vars: dict[str, str],
    *,
    template_key: str,
) -> tuple[dict[str, Any], str]:
    out: dict[str, Any] = {}

    proxmox_url = str(proxmox_vars.get("proxmox_url") or "").strip()
    proxmox_token_id = str(proxmox_vars.get("proxmox_token_id") or "").strip()
    proxmox_token_secret = str(proxmox_vars.get("proxmox_token_secret") or "").strip()
    proxmox_node = str(proxmox_vars.get("proxmox_node") or "").strip()
    if not proxmox_url or not proxmox_token_id or not proxmox_token_secret or not proxmox_node:
        return out, "proxmox credentials missing proxmox_url/proxmox_token_id/proxmox_token_secret/proxmox_node"

    out["proxmox_url"] = proxmox_url
    out["proxmox_token_id"] = proxmox_token_id
    out["proxmox_token_secret"] = proxmox_token_secret
    out["proxmox_node"] = proxmox_node

    skip_tls = str(
        proxmox_vars.get("proxmox_skip_tls")
        or proxmox_vars.get("proxmox_skip_tls_verify")
        or ""
    ).strip().lower()
    if skip_tls in ("true", "false"):
        out["proxmox_skip_tls"] = skip_tls == "true"

    passthrough = (
        "storage_pool",
        "storage_iso",
        "network_bridge",
        "http_bind_address",
        "http_port",
        "ssh_public_key",
        "ssh_password_hash",
    )
    for key in passthrough:
        value = str(proxmox_vars.get(key) or "").strip()
        if not value:
            continue
        if key == "http_port":
            parsed_port = as_port(value)
            if parsed_port is None:
                return out, "proxmox credentials http_port must be an integer in range 1..65535"
            out[key] = int(parsed_port)
            continue
        out[key] = value

    copy_map = {
        "name": "name",
        "description": "description",
        "pool": "pool",
        "vmid": "vmid",
        "cpu_cores": "cpu_cores",
        "cpu_sockets": "cpu_sockets",
        "memory_mb": "memory",
        "disk_size": "disk_size",
        "disk_format": "disk_format",
        "cpu_type": "cpu_type",
        "os_type": "os",
        "network_bridge": "network_bridge",
        "communicator": "communicator",
        "ssh_username": "ssh_username",
        "ssh_password": "ssh_password",
        "winrm_username": "winrm_username",
        "winrm_password": "winrm_password",
    }
    for src, dst in copy_map.items():
        if src not in inputs:
            continue
        value = inputs.get(src)
        if value is None:
            continue
        if isinstance(value, str):
            token = value.strip()
            if token == "":
                continue
            token_lower = token.lower()
            if str(template_key or "").lower().startswith("windows-"):
                # Guard against Linux-oriented defaults leaking into Windows template builds.
                if src == "communicator" and token_lower == "ssh":
                    continue
                if src == "os_type" and token_lower == "l26":
                    continue
            out[dst] = token
            continue
        out[dst] = value

    disk_size_gb = as_positive_int(inputs.get("disk_size_gb"))
    if disk_size_gb is not None:
        out["disk_size"] = f"{disk_size_gb}G"

    return out, ""
