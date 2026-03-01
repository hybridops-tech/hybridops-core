"""Inventory rendering helpers for the Ansible config driver."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from hyops.runtime.coerce import as_bool, as_int

_GROUP_NAME_RE = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_-]*$")
_HOST_ALIAS_RE = re.compile(r"^[A-Za-z0-9_.-]+$")


def _ssh_access_mode(inputs: dict[str, Any]) -> str:
    token = str(inputs.get("ssh_access_mode") or "").strip().lower()
    if token in {"direct", "bastion-explicit", "gcp-iap"}:
        return token
    if str(inputs.get("ssh_proxy_jump_host") or "").strip():
        return "bastion-explicit"
    return "direct"


def _build_bastion_common_args(
    *,
    ssh_private_key_file: str,
    proxy_host: str,
    proxy_user: str,
    proxy_port: int,
) -> str:
    proxy_cmd_parts = [
        "ssh",
        "-p",
        str(int(proxy_port)),
        "-o",
        "StrictHostKeyChecking=no",
        "-o",
        "UserKnownHostsFile=/dev/null",
    ]
    if ssh_private_key_file:
        proxy_cmd_parts.extend(["-i", ssh_private_key_file])
    proxy_cmd_parts.append(f"{proxy_user}@{proxy_host}")
    proxy_cmd_parts.extend(["nc", "%h", "%p"])
    proxy_cmd = " ".join(proxy_cmd_parts)
    return (
        f"-o ProxyCommand=\"{proxy_cmd}\" "
        "-o StrictHostKeyChecking=no "
        "-o UserKnownHostsFile=/dev/null"
    )


def _build_gcp_iap_common_args(
    *,
    instance_name: str,
    project_id: str,
    zone: str,
) -> str:
    proxy_cmd = (
        "gcloud compute start-iap-tunnel "
        f"{instance_name} %p --listen-on-stdin --project {project_id} --zone {zone} --verbosity=warning"
    )
    return (
        f"-o ProxyCommand=\"{proxy_cmd}\" "
        "-o StrictHostKeyChecking=no "
        "-o UserKnownHostsFile=/dev/null"
    )


def _write_inventory_groups(path: Path, inputs: dict[str, Any], inventory_groups: dict[str, Any]) -> str:
    target_user = str(inputs.get("target_user") or "").strip() or "root"
    target_port = as_int(inputs.get("target_port"), default=22)
    if target_port <= 0 or target_port > 65535:
        return "inputs.target_port must be between 1 and 65535"

    ssh_private_key_file = str(inputs.get("ssh_private_key_file") or "").strip()
    become = as_bool(inputs.get("become"), default=True)
    become_user = str(inputs.get("become_user") or "").strip() or "root"

    access_mode = _ssh_access_mode(inputs)
    proxy_host = str(inputs.get("ssh_proxy_jump_host") or "").strip()
    proxy_user = str(inputs.get("ssh_proxy_jump_user") or "").strip() or "root"
    proxy_port = as_int(inputs.get("ssh_proxy_jump_port"), default=22)
    if proxy_host and (proxy_port <= 0 or proxy_port > 65535):
        return "inputs.ssh_proxy_jump_port must be between 1 and 65535"

    lines: list[str] = []
    group_names: list[str] = []

    for raw_group, raw_hosts in inventory_groups.items():
        group = str(raw_group or "").strip()
        if not group or not _GROUP_NAME_RE.fullmatch(group):
            return "inputs.inventory_groups keys must match ^[A-Za-z0-9_][A-Za-z0-9_-]*$"

        if not isinstance(raw_hosts, list) or not raw_hosts:
            return f"inputs.inventory_groups[{group!r}] must be a non-empty list"

        group_names.append(group)
        lines.append(f"[{group}]")
        for idx, item in enumerate(raw_hosts, start=1):
            if not isinstance(item, dict):
                return f"inputs.inventory_groups[{group!r}][{idx}] must be a mapping"
            name = str(item.get("name") or "").strip()
            host = str(item.get("host") or item.get("ansible_host") or "").strip()
            if not name or not _HOST_ALIAS_RE.fullmatch(name):
                return f"inputs.inventory_groups[{group!r}][{idx}].name must match ^[A-Za-z0-9_.-]+$"
            if not host:
                return f"inputs.inventory_groups[{group!r}][{idx}].host is required"
            ansible_host = host
            common_args = ""
            if access_mode == "bastion-explicit":
                if not proxy_host:
                    return "inputs.ssh_access_mode=bastion-explicit requires inputs.ssh_proxy_jump_host"
                common_args = _build_bastion_common_args(
                    ssh_private_key_file=ssh_private_key_file,
                    proxy_host=proxy_host,
                    proxy_user=proxy_user,
                    proxy_port=proxy_port,
                )
            elif access_mode == "gcp-iap":
                instance_name = str(item.get("gcp_iap_instance") or "").strip()
                project_id = str(item.get("gcp_iap_project_id") or inputs.get("gcp_iap_project_id") or "").strip()
                zone = str(item.get("gcp_iap_zone") or inputs.get("gcp_iap_zone") or "").strip()
                if not instance_name or not project_id or not zone:
                    return (
                        f"inputs.inventory_groups[{group!r}][{idx}] requires gcp_iap_instance, "
                        "gcp_iap_project_id, and gcp_iap_zone when inputs.ssh_access_mode=gcp-iap"
                    )
                ansible_host = instance_name
                common_args = _build_gcp_iap_common_args(
                    instance_name=instance_name,
                    project_id=project_id,
                    zone=zone,
                )
            host_parts = [name, f"ansible_host={ansible_host}"]
            if common_args:
                host_parts.append(f"ansible_ssh_common_args='{common_args}'")
            lines.append(" ".join(host_parts))
        lines.append("")

    lines.append("[targets:children]")
    lines.extend(group_names)
    lines.append("")

    lines.extend(
        [
            "[targets:vars]",
            f"ansible_user={target_user}",
            f"ansible_port={int(target_port)}",
            "ansible_python_interpreter=/usr/bin/python3",
        ]
    )
    if ssh_private_key_file:
        lines.append(f"ansible_ssh_private_key_file={ssh_private_key_file}")
    lines.append(f"ansible_become={'true' if become else 'false'}")
    # Do not force ansible_become_user=root: it prevents roles/tasks from
    # switching to service users (e.g. postgres) when required.
    if become_user and become_user != "root":
        lines.append(f"ansible_become_user={become_user}")
    lines.append("")

    path.write_text("\n".join(lines), encoding="utf-8")
    return ""


def write_inventory(path: Path, inputs: dict[str, Any]) -> str:
    inventory_groups = inputs.get("inventory_groups")
    if isinstance(inventory_groups, dict) and inventory_groups:
        return _write_inventory_groups(path, inputs, inventory_groups)

    target_host = str(inputs.get("target_host") or "").strip()
    if not target_host:
        return "inputs.target_host is required"

    target_user = str(inputs.get("target_user") or "").strip() or "root"
    target_port = as_int(inputs.get("target_port"), default=22)
    if target_port <= 0 or target_port > 65535:
        return "inputs.target_port must be between 1 and 65535"

    ssh_private_key_file = str(inputs.get("ssh_private_key_file") or "").strip()
    become = as_bool(inputs.get("become"), default=True)
    become_user = str(inputs.get("become_user") or "").strip() or "root"

    parts = [
        "hyops_target",
        f"ansible_host={target_host}",
        f"ansible_user={target_user}",
        f"ansible_port={target_port}",
        "ansible_python_interpreter=/usr/bin/python3",
    ]
    if ssh_private_key_file:
        parts.append(f"ansible_ssh_private_key_file={ssh_private_key_file}")

    proxy_host = str(inputs.get("ssh_proxy_jump_host") or "").strip()
    access_mode = _ssh_access_mode(inputs)
    if access_mode == "gcp-iap":
        instance_name = str(inputs.get("gcp_iap_instance") or "").strip()
        project_id = str(inputs.get("gcp_iap_project_id") or "").strip()
        zone = str(inputs.get("gcp_iap_zone") or "").strip()
        if not instance_name or not project_id or not zone:
            return "inputs.gcp_iap_instance, inputs.gcp_iap_project_id, and inputs.gcp_iap_zone are required when inputs.ssh_access_mode=gcp-iap"
        common_args = _build_gcp_iap_common_args(
            instance_name=instance_name,
            project_id=project_id,
            zone=zone,
        )
        parts[1] = f"ansible_host={instance_name}"
        parts.append(f"ansible_ssh_common_args='{common_args}'")
    elif proxy_host:
        proxy_user = str(inputs.get("ssh_proxy_jump_user") or "").strip() or "root"
        proxy_port = as_int(inputs.get("ssh_proxy_jump_port"), default=22)
        if proxy_port <= 0 or proxy_port > 65535:
            return "inputs.ssh_proxy_jump_port must be between 1 and 65535"
        common_args = _build_bastion_common_args(
            ssh_private_key_file=ssh_private_key_file,
            proxy_host=proxy_host,
            proxy_user=proxy_user,
            proxy_port=proxy_port,
        )
        parts.append(f"ansible_ssh_common_args='{common_args}'")

    lines = [
        "[targets]",
        " ".join(parts),
        "",
        "[targets:vars]",
        f"ansible_become={'true' if become else 'false'}",
    ]
    # Do not force ansible_become_user=root: it prevents roles/tasks from
    # switching to service users (e.g. postgres) when required.
    if become_user and become_user != "root":
        lines.append(f"ansible_become_user={become_user}")
    lines.append("")

    path.write_text("\n".join(lines), encoding="utf-8")
    return ""
