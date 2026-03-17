"""
purpose: Shared validation helpers for EVE-NG Linux modules.
Architecture Decision: ADR-N/A (linux eve-ng module contract)
maintainer: HybridOps.Tech
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import ipaddress
from pathlib import Path
from typing import Any

from hyops.validators.common import (
    normalize_lifecycle_command,
    require_bool,
    require_mapping,
    require_non_empty_str,
    require_port,
)


_PLACEHOLDER_HOSTS = {"0.0.0.0", "127.0.0.1"}


def require_secret_seeding(
    *,
    load_vault_env: bool,
    required_env: list[str],
    env_keys: list[str],
    module_ref: str,
) -> None:
    missing_from_contract = [key for key in env_keys if key not in required_env]
    if missing_from_contract:
        missing = ", ".join(missing_from_contract)
        raise ValueError(
            f"inputs.required_env must include: {missing} when {module_ref} is not running in destroy mode"
        )

    if load_vault_env:
        return

    missing_seeded = [key for key in env_keys if not str(os.environ.get(key) or "").strip()]
    if missing_seeded:
        missing = ", ".join(missing_seeded)
        raise ValueError(
            f"{module_ref} requires seeded secrets before validate/apply: {missing}. "
            "Either export them in the shell, or set inputs.load_vault_env=true and persist them with "
            f"hyops secrets ensure --env <env> {' '.join(missing_seeded)}."
        )


def parse_os_release(payload: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for raw in (payload or "").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key:
            out[key] = value
    return out


def _ssh_base_argv(*, target_port: int, ssh_private_key_file: str) -> list[str]:
    ssh_bin = shutil.which("ssh")
    if not ssh_bin:
        raise ValueError("missing command: ssh")

    argv = [
        ssh_bin,
        "-o",
        "BatchMode=yes",
        "-o",
        "StrictHostKeyChecking=no",
        "-o",
        "UserKnownHostsFile=/dev/null",
        "-o",
        "ConnectTimeout=8",
        "-o",
        "LogLevel=ERROR",
        "-p",
        str(target_port),
    ]

    if ssh_private_key_file:
        key_path = Path(ssh_private_key_file).expanduser()
        if not key_path.is_file():
            raise ValueError(f"inputs.ssh_private_key_file not found: {key_path}")
        argv.extend(["-i", str(key_path), "-o", "IdentitiesOnly=yes"])

    return argv


def _attach_bastion_proxy(
    argv: list[str],
    *,
    ssh_private_key_file: str,
    proxy_host: str,
    proxy_user: str,
    proxy_port: int,
) -> None:
    proxy_cmd_parts = [
        "ssh",
        "-p",
        str(proxy_port),
        "-o",
        "BatchMode=yes",
        "-o",
        "StrictHostKeyChecking=no",
        "-o",
        "UserKnownHostsFile=/dev/null",
    ]
    if ssh_private_key_file:
        proxy_cmd_parts.extend(["-i", ssh_private_key_file, "-o", "IdentitiesOnly=yes"])
    proxy_cmd_parts.append(f"{proxy_user}@{proxy_host}")
    proxy_cmd_parts.extend(["nc", "%h", "%p"])
    argv.extend(["-o", f"ProxyCommand={' '.join(proxy_cmd_parts)}"])


def _attach_gcp_iap_proxy(
    argv: list[str],
    *,
    instance_name: str,
    project_id: str,
    zone: str,
) -> None:
    gcloud_bin = shutil.which("gcloud")
    if not gcloud_bin:
        raise ValueError("missing command: gcloud (required for inputs.ssh_access_mode=gcp-iap)")
    proxy_cmd = (
        f"{gcloud_bin} compute start-iap-tunnel {instance_name} %p "
        f"--listen-on-stdin --project {project_id} --zone {zone} --verbosity=warning"
    )
    argv.extend(["-o", f"ProxyCommand={proxy_cmd}"])


def _resolve_auto_proxy_jump() -> tuple[str, str]:
    runtime_root_raw = str(os.environ.get("HYOPS_RUNTIME_ROOT") or "").strip()
    if runtime_root_raw:
        runtime_root = Path(runtime_root_raw).expanduser().resolve()
    else:
        env_name = str(os.environ.get("HYOPS_ENV") or "").strip()
        if not env_name:
            return "", ""
        runtime_root = (Path.home() / ".hybridops" / "envs" / env_name).resolve()
    ready_path = runtime_root / "meta" / "proxmox.ready.json"
    if not ready_path.is_file():
        return "", ""

    try:
        payload = json.loads(ready_path.read_text(encoding="utf-8"))
    except Exception:
        return "", ""
    if not isinstance(payload, dict):
        return "", ""

    runtime = payload.get("runtime")
    if not isinstance(runtime, dict):
        return "", ""

    proxy_host = str(runtime.get("api_ip") or "").strip()
    if not proxy_host:
        return "", ""

    credentials_path = runtime_root / "credentials" / "proxmox.credentials.tfvars"
    proxy_user = ""
    if credentials_path.is_file():
        for raw_line in credentials_path.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            if key.strip() != "proxmox_ssh_username":
                continue
            proxy_user = value.strip().strip('"').strip("'")
            break

    return proxy_host, proxy_user


def run_remote_command(
    *,
    target_host: str,
    target_user: str,
    target_port: int,
    ssh_private_key_file: str,
    ssh_access_mode: str,
    proxy_host: str,
    proxy_user: str,
    proxy_port: int,
    gcp_iap_instance: str,
    gcp_iap_project_id: str,
    gcp_iap_zone: str,
    command: str,
    timeout: int = 15,
) -> str:
    argv = _ssh_base_argv(target_port=target_port, ssh_private_key_file=ssh_private_key_file)

    if ssh_access_mode == "bastion-explicit":
        _attach_bastion_proxy(
            argv,
            ssh_private_key_file=ssh_private_key_file,
            proxy_host=proxy_host,
            proxy_user=proxy_user,
            proxy_port=proxy_port,
        )
    elif ssh_access_mode == "gcp-iap":
        _attach_gcp_iap_proxy(
            argv,
            instance_name=gcp_iap_instance,
            project_id=gcp_iap_project_id,
            zone=gcp_iap_zone,
        )

    argv.extend([f"{target_user}@{target_host}", command])

    try:
        proc = subprocess.run(argv, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired as exc:
        raise ValueError(f"ssh check timed out after {exc.timeout}s (host={target_host})") from exc

    if int(proc.returncode) != 0:
        detail = (proc.stderr or "").strip() or (proc.stdout or "").strip() or f"rc={proc.returncode}"
        detail_lower = detail.lower()
        if ssh_access_mode == "gcp-iap" and "not authorized" in detail_lower and "iap" in detail_lower:
            raise ValueError(
                "gcp-iap tunnel authorisation failed "
                f"(instance={gcp_iap_instance} project={gcp_iap_project_id} zone={gcp_iap_zone} host={target_host}). "
                "Confirm the active gcloud identity has IAP-secured Tunnel User access and OS/Login or SSH access."
            )
        raise ValueError(f"ssh check failed (host={target_host}): {detail}")

    return proc.stdout


def read_target_os_release(
    *,
    target_host: str,
    target_user: str,
    target_port: int,
    ssh_private_key_file: str,
    ssh_access_mode: str,
    proxy_host: str,
    proxy_user: str,
    proxy_port: int,
    gcp_iap_instance: str,
    gcp_iap_project_id: str,
    gcp_iap_zone: str,
) -> dict[str, str]:
    return parse_os_release(
        run_remote_command(
            target_host=target_host,
            target_user=target_user,
            target_port=target_port,
            ssh_private_key_file=ssh_private_key_file,
            ssh_access_mode=ssh_access_mode,
            proxy_host=proxy_host,
            proxy_user=proxy_user,
            proxy_port=proxy_port,
            gcp_iap_instance=gcp_iap_instance,
            gcp_iap_project_id=gcp_iap_project_id,
            gcp_iap_zone=gcp_iap_zone,
            command="cat /etc/os-release",
        )
    )


def require_ubuntu_22(target_os: dict[str, str]) -> None:
    distro_id = str(target_os.get("ID") or "").strip().lower()
    version_id = str(target_os.get("VERSION_ID") or "").strip()
    codename = str(target_os.get("VERSION_CODENAME") or "").strip().lower()
    pretty = str(target_os.get("PRETTY_NAME") or "").strip()

    ok = distro_id == "ubuntu" and version_id.startswith("22.04")
    if ok:
        return

    detected = pretty or f"id={distro_id or 'unknown'} version_id={version_id or 'unknown'} codename={codename or 'unknown'}"
    raise ValueError(
        "EVE-NG modules support Ubuntu 22.04 (Jammy) only. "
        f"Detected: {detected}. "
        "Use a Jammy host, or use a different module for your OS."
    )


def require_eveng_host(
    *,
    target_host: str,
    target_user: str,
    target_port: int,
    ssh_private_key_file: str,
    ssh_access_mode: str,
    proxy_host: str,
    proxy_user: str,
    proxy_port: int,
    gcp_iap_instance: str,
    gcp_iap_project_id: str,
    gcp_iap_zone: str,
) -> None:
    run_remote_command(
        target_host=target_host,
        target_user=target_user,
        target_port=target_port,
        ssh_private_key_file=ssh_private_key_file,
        ssh_access_mode=ssh_access_mode,
        proxy_host=proxy_host,
        proxy_user=proxy_user,
        proxy_port=proxy_port,
        gcp_iap_instance=gcp_iap_instance,
        gcp_iap_project_id=gcp_iap_project_id,
        gcp_iap_zone=gcp_iap_zone,
        command="test -d /opt/unetlab && test -d /opt/unetlab/addons && test -d /opt/unetlab/labs",
        timeout=12,
    )


def resolve_target(data: dict[str, Any], *, module_ref: str, ssh_access_mode: str) -> tuple[str, str, str, str]:
    inventory_groups = data.get("inventory_groups")
    if isinstance(inventory_groups, dict) and inventory_groups:
        targets = inventory_groups.get("targets")
        if not isinstance(targets, list) or not targets:
            raise ValueError("inputs.inventory_groups must include group 'targets' with exactly one host")
        if len(targets) != 1:
            raise ValueError(f"inputs.inventory_groups.targets must contain exactly one host for {module_ref}")
        item = targets[0]
        if not isinstance(item, dict):
            raise ValueError("inputs.inventory_groups.targets[1] must be a mapping")
        host = require_non_empty_str(
            item.get("host") or item.get("ansible_host"),
            "inputs.inventory_groups.targets[1].host",
        )
        instance = str(item.get("gcp_iap_instance") or "").strip()
        zone = str(item.get("gcp_iap_zone") or "").strip()
        project_id = str(item.get("gcp_iap_project_id") or "").strip()
        if ssh_access_mode == "gcp-iap" and host not in _PLACEHOLDER_HOSTS:
            raw_tags = item.get("tags")
            tags = {str(tag).strip() for tag in raw_tags} if isinstance(raw_tags, list) else set()
            if "allow-iap-ssh" not in tags:
                raise ValueError(
                    "inputs.ssh_access_mode=gcp-iap requires the target VM/network policy to allow IAP SSH. "
                    "The resolved target host does not publish tag 'allow-iap-ssh'."
                )
        return host, instance, zone, project_id

    target_host = str(data.get("target_host") or "").strip()
    if target_host:
        return (
            target_host,
            str(data.get("gcp_iap_instance") or "").strip(),
            str(data.get("gcp_iap_zone") or "").strip(),
            str(data.get("gcp_iap_project_id") or "").strip(),
        )

    inventory_state_ref = str(data.get("inventory_state_ref") or "").strip()
    if inventory_state_ref:
        inventory_vm_groups = data.get("inventory_vm_groups")
        if not isinstance(inventory_vm_groups, dict) or not inventory_vm_groups:
            raise ValueError("inputs.inventory_vm_groups must be a non-empty mapping when inputs.inventory_state_ref is set")
        targets = inventory_vm_groups.get("targets")
        if not isinstance(targets, list) or not targets:
            raise ValueError("inputs.inventory_vm_groups must include key 'targets' with exactly one VM key")
        if len(targets) != 1:
            raise ValueError(f"inputs.inventory_vm_groups.targets must contain exactly one VM key for {module_ref}")
        return "", "", "", ""

    target_state_ref = str(data.get("target_state_ref") or "").strip()
    if target_state_ref:
        require_non_empty_str(data.get("target_vm_key"), "inputs.target_vm_key")
        return "", "", "", ""

    raise ValueError(
        "provide one of: inputs.target_host, inputs.target_state_ref + inputs.target_vm_key, "
        "or inputs.inventory_state_ref + inputs.inventory_vm_groups"
    )


def validate_target_access(
    data: dict[str, Any],
    *,
    module_ref: str,
    require_ubuntu: bool,
    require_eveng: bool,
) -> dict[str, Any]:
    lifecycle_command = normalize_lifecycle_command(data)
    is_destroy = lifecycle_command == "destroy"
    defer_connectivity_probe = False

    ssh_access_mode = str(data.get("ssh_access_mode") or "direct").strip().lower() or "direct"
    if ssh_access_mode not in {"direct", "bastion-explicit", "gcp-iap"}:
        raise ValueError("inputs.ssh_access_mode must be one of: direct, bastion-explicit, gcp-iap")

    target_user = require_non_empty_str(data.get("target_user"), "inputs.target_user")
    target_port = require_port(data.get("target_port"), "inputs.target_port")

    ssh_private_key_file = ""
    if data.get("ssh_private_key_file") is not None and str(data.get("ssh_private_key_file") or "").strip():
        ssh_private_key_file = require_non_empty_str(data.get("ssh_private_key_file"), "inputs.ssh_private_key_file")

    if data.get("ssh_proxy_jump_auto") is not None:
        require_bool(data.get("ssh_proxy_jump_auto"), "inputs.ssh_proxy_jump_auto")

    proxy_host = str(data.get("ssh_proxy_jump_host") or "").strip()
    proxy_user = str(data.get("ssh_proxy_jump_user") or "").strip() or "opsadmin"
    proxy_port = 22
    if data.get("ssh_proxy_jump_port") is not None:
        proxy_port = require_port(data.get("ssh_proxy_jump_port"), "inputs.ssh_proxy_jump_port")
    if ssh_access_mode == "bastion-explicit":
        require_non_empty_str(data.get("ssh_proxy_jump_host"), "inputs.ssh_proxy_jump_host")
    elif (
        ssh_access_mode == "direct"
        and proxy_host == ""
        and bool(data.get("ssh_proxy_jump_auto"))
    ):
        proxy_host, detected_user = _resolve_auto_proxy_jump()
        if proxy_host:
            ssh_access_mode = "bastion-explicit"
            if not str(data.get("ssh_proxy_jump_user") or "").strip() and detected_user:
                proxy_user = detected_user
        else:
            target_hint = str(data.get("target_host") or "").strip()
            if target_hint:
                try:
                    ip_obj = ipaddress.ip_address(target_hint)
                except Exception:
                    ip_obj = None
                if ip_obj is not None and ip_obj.is_private:
                    defer_connectivity_probe = True

    if data.get("become") is not None:
        require_bool(data.get("become"), "inputs.become")
    if data.get("become_user") is not None:
        require_non_empty_str(data.get("become_user"), "inputs.become_user")
    if data.get("connectivity_check") is not None:
        require_bool(data.get("connectivity_check"), "inputs.connectivity_check")
    if data.get("connectivity_timeout_s") is not None:
        require_port(data.get("connectivity_timeout_s"), "inputs.connectivity_timeout_s")
    if data.get("connectivity_wait_s") is not None:
        value = data.get("connectivity_wait_s")
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise ValueError("inputs.connectivity_wait_s must be an integer >= 0")
    if data.get("load_vault_env") is not None:
        require_bool(data.get("load_vault_env"), "inputs.load_vault_env")

    target_host, resolved_iap_instance, resolved_iap_zone, resolved_iap_project_id = resolve_target(
        data,
        module_ref=module_ref,
        ssh_access_mode=ssh_access_mode,
    )
    if (
        ssh_access_mode == "direct"
        and not proxy_host
        and bool(data.get("ssh_proxy_jump_auto"))
        and target_host
        and target_host not in _PLACEHOLDER_HOSTS
    ):
        try:
            target_ip = ipaddress.ip_address(target_host)
        except Exception:
            target_ip = None
        if target_ip is not None and target_ip.is_private:
            defer_connectivity_probe = True

    gcp_iap_instance = str(data.get("gcp_iap_instance") or resolved_iap_instance or "").strip()
    gcp_iap_project_id = str(data.get("gcp_iap_project_id") or resolved_iap_project_id or "").strip()
    gcp_iap_zone = str(data.get("gcp_iap_zone") or resolved_iap_zone or "").strip()
    if ssh_access_mode == "gcp-iap":
        unresolved_future_target = (
            target_host in {"", *_PLACEHOLDER_HOSTS}
            and (
                str(data.get("inventory_state_ref") or "").strip()
                or str(data.get("target_state_ref") or "").strip()
            )
        )
        if not unresolved_future_target:
            require_non_empty_str(gcp_iap_instance, "inputs.gcp_iap_instance")
            require_non_empty_str(gcp_iap_project_id, "inputs.gcp_iap_project_id")
            require_non_empty_str(gcp_iap_zone, "inputs.gcp_iap_zone")

    remote_kwargs = {
        "target_host": target_host,
        "target_user": target_user,
        "target_port": target_port,
        "ssh_private_key_file": ssh_private_key_file,
        "ssh_access_mode": ssh_access_mode,
        "proxy_host": proxy_host,
        "proxy_user": proxy_user,
        "proxy_port": proxy_port,
        "gcp_iap_instance": gcp_iap_instance,
        "gcp_iap_project_id": gcp_iap_project_id,
        "gcp_iap_zone": gcp_iap_zone,
    }

    if not is_destroy and target_host and target_host not in _PLACEHOLDER_HOSTS and not defer_connectivity_probe:
        if require_ubuntu:
            target_os = read_target_os_release(**remote_kwargs)
            require_ubuntu_22(target_os)
        if require_eveng:
            try:
                require_eveng_host(**remote_kwargs)
            except ValueError as exc:
                raise ValueError(
                    f"EVE-NG base was not detected on the target host for {module_ref}. "
                    "Run platform/linux/eve-ng first, or target an existing EVE-NG host. "
                    f"Details: {exc}"
                ) from exc

    remote_kwargs.update(
        {
            "is_destroy": is_destroy,
            "ssh_access_mode": ssh_access_mode,
            "target_user": target_user,
            "target_port": target_port,
            "target_host": target_host,
            "defer_connectivity_probe": defer_connectivity_probe,
        }
    )
    return remote_kwargs
