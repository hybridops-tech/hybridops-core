"""Read-only readiness checks for Proxmox image builds."""

from __future__ import annotations

from typing import Any, Mapping
from urllib.parse import urlparse

from hyops.runtime.coerce import as_bool

from .proxmox_api import proxmox_storage_content_exists, proxmox_token_has_privilege


def _effective_bool(name: str, base_vars: Mapping[str, Any], env: Mapping[str, str]) -> bool:
    override = str(env.get(f"PKR_VAR_{name}") or "").strip()
    if override:
        return bool(as_bool(override, default=False))
    return bool(as_bool(base_vars.get(name), default=False))


def _effective_string(name: str, base_vars: Mapping[str, Any], env: Mapping[str, str]) -> str:
    override = str(env.get(f"PKR_VAR_{name}") or "").strip()
    return override or str(base_vars.get(name) or "").strip()


def validate_proxmox_build_readiness(
    *,
    proxmox_url: str,
    proxmox_node: str,
    proxmox_token_id: str,
    proxmox_token_secret: str,
    skip_tls: bool,
    runtime_vars: Mapping[str, Any],
    base_vars: Mapping[str, Any],
    env: Mapping[str, str],
) -> str:
    bridge = str(runtime_vars.get("network_bridge") or "").strip()
    if not bridge:
        return "network_bridge resolved to an empty value"

    bridge_path = f"/sdn/zones/localnetwork/{bridge}"
    has_bridge_access, bridge_error = proxmox_token_has_privilege(
        proxmox_url=proxmox_url,
        proxmox_token_id=proxmox_token_id,
        proxmox_token_secret=proxmox_token_secret,
        skip_tls=skip_tls,
        resource_path=bridge_path,
        privilege="SDN.Use",
    )
    if bridge_error:
        return f"bridge authority check failed for {bridge_path}: {bridge_error}"
    if not has_bridge_access:
        return f"Proxmox token lacks SDN.Use on {bridge_path}; rerun hyops init proxmox --bootstrap"

    iso_download = _effective_bool("iso_download", base_vars, env)
    iso_file = _effective_string("iso_file", base_vars, env)
    if iso_download:
        iso_url = _effective_string("iso_url", base_vars, env)
        parsed = urlparse(iso_url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            return "ISO download is enabled but iso_url is not a valid HTTP(S) URL"
        checksum = _effective_string("iso_checksum", base_vars, env)
        if not checksum:
            return "ISO download is enabled but iso_checksum is empty"

        storage = str(runtime_vars.get("storage_iso") or "").strip()
        storage_path = f"/storage/{storage}"
        can_allocate, allocation_error = proxmox_token_has_privilege(
            proxmox_url=proxmox_url,
            proxmox_token_id=proxmox_token_id,
            proxmox_token_secret=proxmox_token_secret,
            skip_tls=skip_tls,
            resource_path=storage_path,
            privilege="Datastore.AllocateTemplate",
        )
        if allocation_error:
            return f"ISO storage authority check failed for {storage_path}: {allocation_error}"
        if not can_allocate:
            return f"Proxmox token lacks Datastore.AllocateTemplate on {storage_path}"

        if _effective_bool("iso_download_pve", base_vars, env):
            can_access_network, network_error = proxmox_token_has_privilege(
                proxmox_url=proxmox_url,
                proxmox_token_id=proxmox_token_id,
                proxmox_token_secret=proxmox_token_secret,
                skip_tls=skip_tls,
                resource_path="/",
                privilege="Sys.AccessNetwork",
            )
            if network_error:
                return f"PVE-side ISO download authority check failed: {network_error}"
            if not can_access_network:
                legacy_privileges = []
                for privilege in ("Sys.Audit", "Sys.Modify"):
                    allowed, privilege_error = proxmox_token_has_privilege(
                        proxmox_url=proxmox_url,
                        proxmox_token_id=proxmox_token_id,
                        proxmox_token_secret=proxmox_token_secret,
                        skip_tls=skip_tls,
                        resource_path="/",
                        privilege=privilege,
                    )
                    if privilege_error:
                        return f"PVE-side ISO download authority check failed: {privilege_error}"
                    legacy_privileges.append(allowed)
                if not all(legacy_privileges):
                    return (
                        "PVE-side ISO download requires Sys.AccessNetwork or the legacy "
                        "Sys.Audit and Sys.Modify privileges on /"
                    )
        return ""

    storage = str(runtime_vars.get("storage_iso") or "").strip()
    if not storage or not iso_file:
        return "cached ISO mode requires storage_iso and iso_file"
    volume_id = f"{storage}:iso/{iso_file}"
    iso_exists, iso_error = proxmox_storage_content_exists(
        proxmox_url=proxmox_url,
        proxmox_node=proxmox_node,
        proxmox_token_id=proxmox_token_id,
        proxmox_token_secret=proxmox_token_secret,
        skip_tls=skip_tls,
        storage=storage,
        volume_id=volume_id,
    )
    if iso_error:
        return f"ISO readiness check failed for {volume_id}: {iso_error}"
    if not iso_exists:
        return (
            f"required ISO is absent: {volume_id}; upload it or enable an authorised ISO download path"
        )
    return ""
