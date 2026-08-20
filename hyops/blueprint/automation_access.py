"""Client material for private access to devices inside network labs."""

from __future__ import annotations

import hashlib
import ipaddress
import os
import re
import shlex
import shutil
import subprocess
from pathlib import Path
from typing import Any

import yaml


_TARGET_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,62}$")


def _safe_name(value: str, *, fallback: str = "device") -> str:
    token = re.sub(r"[^A-Za-z0-9_.-]+", "-", str(value or "").strip()).strip("-.")
    if not token or not token[0].isalnum():
        token = fallback
    return token[:63]


def _write_private(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    try:
        path.parent.chmod(0o700)
    except OSError:
        pass
    temporary = path.with_name(f".{path.name}.tmp-{os.getpid()}")
    temporary.write_text(content, encoding="utf-8")
    temporary.chmod(0o600)
    temporary.replace(path)


def parse_dnsmasq_leases(text: str, management_cidr: str, *, default_user: str) -> list[dict[str, Any]]:
    """Return safe target candidates from a dnsmasq lease file."""

    network = ipaddress.ip_network(management_cidr, strict=False)
    candidates: list[dict[str, Any]] = []
    used_names: set[str] = set()
    for line in str(text or "").splitlines():
        fields = line.split()
        if len(fields) < 4:
            continue
        mac, address, hostname = fields[1], fields[2], fields[3]
        try:
            ip = ipaddress.ip_address(address)
        except ValueError:
            continue
        if ip not in network:
            continue
        base = _safe_name(hostname if hostname not in {"", "*"} else f"device-{str(ip).split('.')[-1]}")
        name = base
        suffix = 2
        while name in used_names:
            name = f"{base[:58]}-{suffix}"
            suffix += 1
        used_names.add(name)
        candidates.append(
            {
                "name": name,
                "host": str(ip),
                "user": default_user,
                "port": 22,
                "mac": mac.lower(),
                "source": "dhcp-lease",
            }
        )
    return sorted(candidates, key=lambda item: ipaddress.ip_address(item["host"]))


def _load_targets(path: Path, management_cidr: str) -> list[dict[str, Any]]:
    try:
        payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError) as exc:
        raise ValueError(f"cannot read automation targets: {path}: {exc}") from exc
    if not isinstance(payload, dict) or not isinstance(payload.get("targets", []), list):
        raise ValueError(f"automation target file must contain a targets list: {path}")

    network = ipaddress.ip_network(management_cidr, strict=False)
    targets: list[dict[str, Any]] = []
    names: set[str] = set()
    for index, raw in enumerate(payload.get("targets") or [], start=1):
        if not isinstance(raw, dict):
            raise ValueError(f"automation targets[{index}] must be a mapping")
        name = str(raw.get("name") or "").strip()
        host = str(raw.get("host") or "").strip()
        user = str(raw.get("user") or "").strip()
        if not _TARGET_NAME_RE.fullmatch(name):
            raise ValueError(f"automation targets[{index}].name is invalid")
        if name in names:
            raise ValueError(f"automation target name is duplicated: {name}")
        names.add(name)
        try:
            address = ipaddress.ip_address(host)
        except ValueError as exc:
            raise ValueError(f"automation target {name} must use an IPv4 address") from exc
        if address not in network:
            raise ValueError(
                f"automation target {name} ({address}) is outside {network}"
            )
        if not user:
            raise ValueError(f"automation target {name} requires user")
        port = int(raw.get("port") or 22)
        if not 1 <= port <= 65535:
            raise ValueError(f"automation target {name} port must be between 1 and 65535")
        identity = str(raw.get("identity_file") or "").strip()
        if identity:
            identity_path = Path(identity).expanduser().resolve()
            if not identity_path.is_file():
                raise ValueError(
                    f"automation target {name} identity file does not exist: {identity_path}"
                )
            identity = str(identity_path)
        groups_raw = raw.get("groups") or []
        if not isinstance(groups_raw, list):
            raise ValueError(f"automation target {name} groups must be a list")
        groups = [_safe_name(str(group), fallback="devices") for group in groups_raw]
        mac = str(raw.get("mac") or "").strip().lower()
        source = str(raw.get("source") or "").strip()
        platform = str(raw.get("platform") or "").strip()
        targets.append(
            {
                "name": name,
                "host": str(address),
                "user": user,
                "port": port,
                "identity_file": identity,
                "groups": list(dict.fromkeys(groups)),
                "mac": mac,
                "source": source,
                "platform": platform,
            }
        )
    return targets


def _target_template(candidates: list[dict[str, Any]], management_label: str) -> str:
    lines = [
        "# Devices reachable through the HybridOps-managed lab network.",
        f"# Connect a management interface to {management_label}, then set the SSH user.",
        "# identity_file is optional; omit it to use agent, keyboard-interactive, or password auth.",
        "version: 1",
        "targets:",
    ]
    if not candidates:
        lines.append("  []")
    else:
        for item in candidates:
            lines.extend(
                [
                    f"  - name: {item['name']}",
                    f"    host: {item['host']}",
                    f"    user: {item['user']}",
                    "    port: 22",
                    f"    mac: {item['mac']}",
                    "    source: dhcp-lease",
                    "    groups: [network_devices]",
                ]
            )
    return "\n".join(lines) + "\n"


def _merge_discovered_targets(
    path: Path,
    candidates: list[dict[str, Any]],
    management_label: str,
) -> list[str]:
    """Add DHCP targets without replacing operator-managed target settings."""

    try:
        payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError) as exc:
        raise ValueError(f"cannot read automation targets: {path}: {exc}") from exc
    if not isinstance(payload, dict) or not isinstance(payload.get("targets", []), list):
        raise ValueError(f"automation target file must contain a targets list: {path}")

    targets = payload.get("targets") or []
    by_mac: dict[str, dict[str, Any]] = {}
    occupied_hosts: set[str] = set()
    occupied_names: set[str] = set()
    for raw in targets:
        if not isinstance(raw, dict):
            continue
        host = str(raw.get("host") or "").strip()
        name = str(raw.get("name") or "").strip()
        mac = str(raw.get("mac") or "").strip().lower()
        source = str(raw.get("source") or "").strip()
        if host:
            occupied_hosts.add(host)
        if name:
            occupied_names.add(name)
        if mac and source == "dhcp-lease":
            by_mac[mac] = raw

    changed = False
    added: list[str] = []
    for candidate in candidates:
        mac = str(candidate.get("mac") or "").lower()
        existing = by_mac.get(mac)
        if existing is not None:
            previous_host = str(existing.get("host") or "").strip()
            current_host = str(candidate["host"])
            if previous_host != current_host and current_host not in occupied_hosts:
                existing["host"] = current_host
                occupied_hosts.discard(previous_host)
                occupied_hosts.add(current_host)
                changed = True
            continue
        if str(candidate["host"]) in occupied_hosts:
            continue

        name = str(candidate["name"])
        base = name
        suffix = 2
        while name in occupied_names:
            name = f"{base[:58]}-{suffix}"
            suffix += 1
        target = {
            "name": name,
            "host": str(candidate["host"]),
            "user": str(candidate["user"]),
            "port": int(candidate.get("port") or 22),
            "mac": mac,
            "source": "dhcp-lease",
            "groups": ["network_devices"],
        }
        targets.append(target)
        by_mac[mac] = target
        occupied_names.add(name)
        occupied_hosts.add(str(candidate["host"]))
        added.append(name)
        changed = True

    if changed:
        content = [
            "# Devices reachable through the HybridOps-managed lab network.",
            f"# DHCP devices on {management_label} are maintained automatically.",
            "# Add static targets or adjust names and credentials when required.",
            yaml.safe_dump({"version": 1, "targets": targets}, sort_keys=False).rstrip(),
            "",
        ]
        _write_private(path, "\n".join(content))
    return added


def automation_session_paths(
    *,
    paths: Any,
    blueprint_ref: str,
    env_name: str,
) -> dict[str, Any]:
    """Return stable client paths and aliases for a blueprint environment."""

    scope = _safe_name(blueprint_ref.replace("@", "-"), fallback="blueprint")
    alias_prefix = _safe_name(f"hyops-{env_name or 'runtime'}", fallback="hyops-runtime")
    config_dir = Path(paths.config_dir) / "automation" / scope
    session_dir = Path(paths.root) / "artifacts" / "access" / scope
    return {
        "scope": scope,
        "alias_prefix": alias_prefix,
        "gateway_alias": f"{alias_prefix}-gateway",
        "config_dir": config_dir,
        "session_dir": session_dir,
        "target_file": config_dir / "targets.yml",
        "ssh_config": session_dir / "ssh_config",
        "inventory": session_dir / "inventory.ini",
        "ansible_config": session_dir / "ansible.cfg",
        "proxy_env": session_dir / "proxy.env",
        "nornir_hosts": session_dir / "nornir-hosts.yml",
        "nornir_groups": session_dir / "nornir-groups.yml",
        "nornir_defaults": session_dir / "nornir-defaults.yml",
        "session_file": session_dir / "session.yml",
    }


def load_automation_targets(path: Path, management_cidr: str) -> list[dict[str, Any]]:
    """Load validated targets for device commands."""

    return _load_targets(path, management_cidr)


def _ssh_config(
    *,
    gateway: dict[str, Any],
    gateway_alias: str,
    target_alias_prefix: str,
    targets: list[dict[str, Any]],
    target_known_hosts: Path,
) -> str:
    lines = [
        "# Valid while the matching hyops blueprint access session is running.",
        f"Host {gateway_alias}",
        f"  HostName {gateway['host']}",
        f"  User {gateway['user']}",
        f"  Port {int(gateway.get('port') or 22)}",
        f"  IdentityFile {gateway['identity_file']}",
        "  IdentitiesOnly yes",
        "  StrictHostKeyChecking accept-new",
        f"  UserKnownHostsFile {gateway['known_hosts_file']}",
        "  LogLevel ERROR",
    ]
    if gateway.get("host_key_alias"):
        lines.append(f"  HostKeyAlias {gateway['host_key_alias']}")
    for target in targets:
        lines.extend(
            [
                "",
                f"Host {target_alias_prefix}-{target['name']}",
                f"  HostName {target['host']}",
                f"  User {target['user']}",
                f"  Port {target['port']}",
                f"  ProxyJump {gateway_alias}",
                "  StrictHostKeyChecking accept-new",
                f"  UserKnownHostsFile {target_known_hosts}",
                "  LogLevel ERROR",
            ]
        )
        if target["identity_file"]:
            lines.extend(
                [
                    f"  IdentityFile {target['identity_file']}",
                    "  IdentitiesOnly yes",
                ]
            )
    return "\n".join(lines) + "\n"


def _inventory(
    targets: list[dict[str, Any]],
    alias_prefix: str,
    ssh_config: Path,
) -> str:
    groups: dict[str, list[dict[str, Any]]] = {"network_devices": list(targets)}
    for target in targets:
        for group in target["groups"]:
            members = groups.setdefault(group, [])
            if target not in members:
                members.append(target)
    lines: list[str] = []
    for group, members in groups.items():
        lines.append(f"[{group}]")
        for target in members:
            lines.append(f"{target['name']} ansible_host={alias_prefix}-{target['name']}")
        lines.append("")
    lines.extend(
        [
            "[all:vars]",
            f"ansible_ssh_common_args='-F {ssh_config}'",
            "",
        ]
    )
    return "\n".join(lines).rstrip() + "\n"


def _nornir_inventory(
    targets: list[dict[str, Any]],
    alias_prefix: str,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    hosts: dict[str, Any] = {}
    groups: dict[str, Any] = {"network_devices": {}}
    for target in targets:
        target_groups = list(target["groups"] or ["network_devices"])
        if "network_devices" not in target_groups:
            target_groups.insert(0, "network_devices")
        for group in target_groups:
            groups.setdefault(group, {})
        host: dict[str, Any] = {
            "hostname": f"{alias_prefix}-{target['name']}",
            "port": target["port"],
            "username": target["user"],
            "groups": target_groups,
            "data": {
                "management_address": target["host"],
                "source": target["source"] or "static",
            },
        }
        if target["platform"]:
            host["platform"] = target["platform"]
        hosts[target["name"]] = host
    return hosts, groups, {}


def prepare_automation_session(
    *,
    paths: Any,
    blueprint_ref: str,
    env_name: str,
    automation: dict[str, Any],
    gateway: dict[str, Any],
    socks_port: int,
    lease_text: str = "",
    target_file_override: str = "",
) -> dict[str, Any]:
    """Create target configuration and client files for one access session."""

    material = automation_session_paths(
        paths=paths,
        blueprint_ref=blueprint_ref,
        env_name=env_name,
    )
    alias_prefix = material["alias_prefix"]
    gateway_alias = material["gateway_alias"]
    config_dir = material["config_dir"]
    session_dir = material["session_dir"]
    target_file = (
        Path(target_file_override).expanduser().resolve()
        if target_file_override
        else config_dir / "targets.yml"
    )
    if target_file_override and not target_file.is_file():
        raise ValueError(f"automation target file does not exist: {target_file}")
    candidates = parse_dnsmasq_leases(
        lease_text,
        automation["management_cidr"],
        default_user=automation["default_user"],
    )
    if not target_file.exists():
        _write_private(
            target_file,
            _target_template(candidates, automation["management_network_label"]),
        )
    new_targets: list[str] = []
    if not target_file_override and candidates:
        new_targets = _merge_discovered_targets(
            target_file,
            candidates,
            automation["management_network_label"],
        )
    targets = _load_targets(target_file, automation["management_cidr"])

    discovered_file = session_dir / "discovered-targets.yml"
    _write_private(
        discovered_file,
        yaml.safe_dump({"version": 1, "targets": candidates}, sort_keys=False),
    )
    target_known_hosts = session_dir / "device_known_hosts"
    target_known_hosts.touch(mode=0o600, exist_ok=True)
    try:
        target_known_hosts.chmod(0o600)
    except OSError:
        pass
    ssh_config = session_dir / "ssh_config"
    inventory = session_dir / "inventory.ini"
    ansible_config = session_dir / "ansible.cfg"
    proxy_env = session_dir / "proxy.env"
    _write_private(
        ssh_config,
        _ssh_config(
            gateway=gateway,
            gateway_alias=gateway_alias,
            target_alias_prefix=alias_prefix,
            targets=targets,
            target_known_hosts=target_known_hosts,
        ),
    )
    _write_private(inventory, _inventory(targets, alias_prefix, ssh_config))
    nornir_hosts = session_dir / "nornir-hosts.yml"
    nornir_groups = session_dir / "nornir-groups.yml"
    nornir_defaults = session_dir / "nornir-defaults.yml"
    hosts_payload, groups_payload, defaults_payload = _nornir_inventory(
        targets,
        alias_prefix,
    )
    _write_private(nornir_hosts, yaml.safe_dump(hosts_payload, sort_keys=False))
    _write_private(nornir_groups, yaml.safe_dump(groups_payload, sort_keys=False))
    _write_private(nornir_defaults, yaml.safe_dump(defaults_payload, sort_keys=False))
    _write_private(
        ansible_config,
        "[defaults]\n"
        f"inventory = {inventory}\n"
        "host_key_checking = True\n\n"
        "[ssh_connection]\n"
        f"ssh_args = -F {ssh_config}\n",
    )
    proxy = f"socks5h://127.0.0.1:{socks_port}"
    _write_private(
        proxy_env,
        f"export HYOPS_SOCKS_PROXY={shlex.quote(proxy)}\n"
        f"export ALL_PROXY={shlex.quote(proxy)}\n",
    )
    session_file = session_dir / "session.yml"
    _write_private(
        session_file,
        yaml.safe_dump(
            {
                "version": 1,
                "blueprint_ref": blueprint_ref,
                "environment": env_name,
                "socks_proxy": proxy,
            },
            sort_keys=False,
        ),
    )
    return {
        "target_file": target_file,
        "discovered_file": discovered_file,
        "ssh_config": ssh_config,
        "inventory": inventory,
        "ansible_config": ansible_config,
        "proxy_env": proxy_env,
        "nornir_hosts": nornir_hosts,
        "nornir_groups": nornir_groups,
        "nornir_defaults": nornir_defaults,
        "session_file": session_file,
        "targets": targets,
        "discovered_count": len(candidates),
        "aliases": [f"{alias_prefix}-{target['name']}" for target in targets],
        "gateway_alias": gateway_alias,
        "socks_proxy": proxy,
        "new_targets": new_targets,
    }


def local_route_conflicts(management_cidr: str) -> list[str]:
    """Return local routes that overlap the requested lab network."""

    network = ipaddress.ip_network(management_cidr, strict=False)
    ip_command = shutil.which("ip")
    if ip_command:
        result = subprocess.run(
            [ip_command, "-o", "-4", "route", "show"],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            check=False,
        )
        routes: list[str] = []
        for line in result.stdout.splitlines():
            destination = line.split(maxsplit=1)[0] if line.strip() else ""
            if destination in {"", "default"}:
                continue
            try:
                candidate = ipaddress.ip_network(destination, strict=False)
            except ValueError:
                continue
            if candidate.overlaps(network):
                routes.append(line.strip())
        return routes

    netstat = shutil.which("netstat")
    if netstat:
        result = subprocess.run(
            [netstat, "-rn", "-f", "inet"],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            check=False,
        )
        routes = []
        for line in result.stdout.splitlines():
            fields = line.split()
            if not fields or fields[0] in {"default", "Destination"}:
                continue
            token = fields[0]
            if "/" not in token:
                continue
            try:
                candidate = ipaddress.ip_network(token, strict=False)
            except ValueError:
                continue
            if candidate.overlaps(network):
                routes.append(line.strip())
        return routes
    return []


def linux_tunnel_plan(scope: str) -> dict[str, Any]:
    """Return a deterministic, environment-scoped point-to-point tunnel plan."""

    digest = hashlib.sha256(scope.encode("utf-8")).digest()
    tunnel_id = 100 + (int.from_bytes(digest[:2], "big") % 800)
    third_octet = 64 + (digest[2] % 64)
    fourth_octet = (digest[3] // 4) * 4
    local_ip = f"169.254.{third_octet}.{fourth_octet + 1}"
    remote_ip = f"169.254.{third_octet}.{fourth_octet + 2}"
    return {
        "tunnel_id": tunnel_id,
        "interface": f"tun{tunnel_id}",
        "local_cidr": f"{local_ip}/30",
        "local_ip": local_ip,
        "remote_cidr": f"{remote_ip}/30",
        "remote_ip": remote_ip,
    }


def build_tunnel_ssh_argv(
    *,
    gateway: dict[str, Any],
    plan: dict[str, Any],
    remote_helper: str,
) -> list[str]:
    """Build a true layer-3 tunnel command through the access host."""

    ssh_command = gateway.get("ssh_command")
    if not isinstance(ssh_command, list) or not ssh_command:
        raise ValueError("automation gateway is missing its SSH command")
    remote_command = shlex.join(
        [
            "sudo",
            "-n",
            remote_helper,
            "session",
            str(plan["interface"]),
            str(plan["remote_cidr"]),
            str(plan["local_ip"]),
        ]
    )
    return [
        *[str(item) for item in ssh_command],
        "-o",
        "ExitOnForwardFailure=yes",
        "-o",
        "Tunnel=point-to-point",
        "-w",
        f"{plan['tunnel_id']}:{plan['tunnel_id']}",
        f"{gateway['user']}@{gateway['host']}",
        remote_command,
    ]
