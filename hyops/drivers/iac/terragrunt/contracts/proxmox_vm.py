"""
purpose: Module contract scaffold for on-prem Proxmox VM capability modules.
maintainer: HybridOps.Tech
"""

from __future__ import annotations

import ipaddress
import json
import copy
import os
import re
import shlex
import shutil
import socket
import ssl
import subprocess
import time
from pathlib import Path
from typing import Any
from urllib import error as urlerror
from urllib import request as urlrequest
from urllib.parse import urlparse

from hyops.runtime.module_state import read_module_state
from hyops.runtime.coerce import as_bool, as_positive_int
from hyops.runtime.credentials import parse_tfvars
from hyops.runtime.netbox_env import resolve_netbox_authority_root
from hyops.runtime.refs import module_id_from_ref
from hyops.runtime.state import read_json

from .base import TerragruntModuleContract


_AUTH_ENV_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_-]{0,63}$")
_SDN_AUTHORITY_ROOT_ENV = "HYOPS_SDN_AUTHORITY_ROOT"
_SDN_AUTHORITY_ENV_ENV = "HYOPS_SDN_AUTHORITY_ENV"
_DEFAULT_SDN_AUTHORITY_ENV = "shared"
_ENV_BRIDGE_ALIAS_MAP: dict[str, dict[str, str]] = {
    "vnetenv": {
        "dev": "vnetdev",
        "development": "vnetdev",
        "stag": "vnetstag",
        "stage": "vnetstag",
        "staging": "vnetstag",
        "prod": "vnetprod",
        "production": "vnetprod",
    },
    "vnetenvdata": {
        "shared": "vnetdata",
        "dev": "vnetddev",
        "development": "vnetddev",
        "stag": "vnetdstg",
        "stage": "vnetdstg",
        "staging": "vnetdstg",
        "prod": "vnetdprd",
        "production": "vnetdprd",
    },
}


def _resolve_env_bridge_alias(alias: str, env_name: str) -> tuple[str, str]:
    alias_token = str(alias or "").strip().lower()
    token = str(env_name or "").strip().lower()
    alias_map = _ENV_BRIDGE_ALIAS_MAP.get(alias_token)
    if not alias_map:
        return "", f"unknown env bridge alias: {alias!r}"
    resolved = alias_map.get(token)
    if resolved:
        return resolved, ""
    if not token:
        supported = ", ".join(sorted(alias_map.keys()))
        return "", (
            f"{alias_token} bridge alias requires HYOPS_ENV to be set "
            f"(supported: {supported})"
        )
    supported = ", ".join(sorted(alias_map.keys()))
    return "", (
        f"{alias_token} bridge alias is unsupported for env={env_name!r} "
        f"(supported: {supported}). Use an explicit bridge (for example vnetmgmt/vnetdata) instead."
    )


def _resolve_bridge_aliases(inputs: dict[str, Any], *, env_name: str) -> tuple[list[str], str]:
    warnings: list[str] = []
    alias_errors: list[str] = []

    def _rewrite_ifaces(ifaces: Any, *, field: str) -> None:
        if not isinstance(ifaces, list):
            return
        for idx, nic in enumerate(ifaces, start=1):
            if not isinstance(nic, dict):
                continue
            bridge = str(nic.get("bridge") or "").strip().lower()
            if bridge not in _ENV_BRIDGE_ALIAS_MAP:
                continue
            resolved_bridge, err = _resolve_env_bridge_alias(bridge, env_name)
            if err:
                alias_errors.append(err)
                continue
            nic["bridge"] = resolved_bridge
            warnings.append(
                f"resolved {field}[{idx}].bridge={bridge} -> {resolved_bridge} (env={env_name})"
            )

    _rewrite_ifaces(inputs.get("interfaces"), field="inputs.interfaces")

    raw_vms = inputs.get("vms")
    if isinstance(raw_vms, dict):
        for vm_name, vm_cfg in raw_vms.items():
            if not isinstance(vm_cfg, dict):
                continue
            _rewrite_ifaces(vm_cfg.get("interfaces"), field=f"inputs.vms[{vm_name}].interfaces")

    vm_bridge = str(inputs.get("vm_bridge") or "").strip().lower()
    if vm_bridge in _ENV_BRIDGE_ALIAS_MAP:
        resolved_bridge, err = _resolve_env_bridge_alias(vm_bridge, env_name)
        if err:
            alias_errors.append(err)
        else:
            inputs["vm_bridge"] = resolved_bridge
            warnings.append(f"resolved inputs.vm_bridge={vm_bridge} -> {resolved_bridge} (env={env_name})")

    if alias_errors:
        # Keep first error deterministic; alias messages already name the alias.
        return warnings, alias_errors[0]

    return warnings, ""


def _pick_template_id(outputs: dict[str, Any], template_key: str) -> int | None:
    scalar_keys = ("template_vm_id", "template_id", "vm_id", "id")
    map_keys = ("template_vm_ids", "template_ids", "vm_ids", "templates", "images", "artifacts", "vms")

    if template_key:
        for key in map_keys:
            container = outputs.get(key)
            if not isinstance(container, dict):
                continue
            if template_key not in container:
                continue
            entry = container.get(template_key)
            if isinstance(entry, dict):
                for child_key in scalar_keys:
                    picked = as_positive_int(entry.get(child_key))
                    if picked is not None:
                        return picked
            picked = as_positive_int(entry)
            if picked is not None:
                return picked
        return None

    for key in scalar_keys:
        picked = as_positive_int(outputs.get(key))
        if picked is not None:
            return picked

    return None


def _as_mapping(value: Any, field: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"{field} must be a mapping")
    return value


def _netbox_ready(state_dir: Path) -> tuple[dict[str, Any], str]:
    # Support centralized NetBox in a different env/root.
    effective_state_dir = state_dir
    runtime_root = state_dir.parent if state_dir.name == "state" else state_dir
    env_map: dict[str, str] = {str(k): str(v) for k, v in os.environ.items()}
    authority_root, authority_err = resolve_netbox_authority_root(env_map, runtime_root)
    if authority_err:
        return {}, f"invalid netbox authority config: {authority_err}"
    if authority_root:
        effective_state_dir = (authority_root / "state").resolve()

    try:
        payload = read_module_state(effective_state_dir, "platform/onprem/netbox")
    except FileNotFoundError:
        hint = "netbox state not found (run: hyops blueprint --env shared --ref onprem/bootstrap-netbox@v1)"
        if authority_root:
            hint += f" OR: set HYOPS_NETBOX_AUTHORITY_ENV and apply NetBox there (authority_root={authority_root})"
        return {}, hint
    except Exception as exc:
        return {}, f"failed to read netbox state: {exc}"

    status = str(payload.get("status") or "").strip().lower()
    if status != "ok":
        return {}, f"netbox state is not ready: status={status or 'unknown'}"
    return payload, ""


def _validate_authority_env_name(env_name: str, *, label: str) -> str:
    env_name = (env_name or "").strip()
    if not env_name:
        raise ValueError(f"{label} env name is empty")
    if "/" in env_name or "\\" in env_name or ".." in env_name:
        raise ValueError(f"invalid {label} env name: {env_name!r}")
    if not _AUTH_ENV_RE.match(env_name):
        raise ValueError(f"invalid {label} env name: {env_name!r}")
    return env_name


def _resolve_sdn_state_dir(state_dir: Path) -> tuple[Path, str]:
    """Resolve the state dir to use as the SDN authority (default shared)."""
    runtime_root = state_dir.parent if state_dir.name == "state" else state_dir
    env_map: dict[str, str] = {str(k): str(v) for k, v in os.environ.items()}

    raw_root = str(env_map.get(_SDN_AUTHORITY_ROOT_ENV) or "").strip()
    if raw_root:
        p = Path(raw_root).expanduser()
        root = p if p.is_absolute() else (runtime_root / p).resolve()
        target_state_dir = (root / "state").resolve()
        return target_state_dir, ""

    raw_env = str(env_map.get(_SDN_AUTHORITY_ENV_ENV) or "").strip()
    if raw_env:
        try:
            env_name = _validate_authority_env_name(raw_env, label="sdn authority")
        except Exception as exc:
            return state_dir, str(exc)
        target_state_dir = (Path.home() / ".hybridops" / "envs" / env_name / "state").resolve()
        return target_state_dir, ""

    target_state_dir = (Path.home() / ".hybridops" / "envs" / _DEFAULT_SDN_AUTHORITY_ENV / "state").resolve()
    return target_state_dir, ""


def _read_network_sdn_state_with_authority(
    *,
    state_dir: Path,
    network_state_ref: str,
) -> tuple[dict[str, Any], list[str], str]:
    warnings: list[str] = []
    effective_state_dir = state_dir
    ref = str(network_state_ref or "").strip()
    if ref.startswith("core/onprem/network-sdn"):
        resolved_state_dir, err = _resolve_sdn_state_dir(state_dir)
        if err:
            return {}, warnings, err
        if resolved_state_dir.resolve() != state_dir.resolve():
            effective_state_dir = resolved_state_dir.resolve()
            warnings.append(f"resolved network_sdn authority state_dir={effective_state_dir}")

    try:
        payload = read_module_state(effective_state_dir, ref)
    except Exception as exc:
        return {}, warnings, f"failed to read {ref}: {exc}"
    return payload, warnings, ""


def _collect_requested_bridges(inputs: dict[str, Any]) -> set[str]:
    bridges: set[str] = set()
    raw_vms = inputs.get("vms")
    if isinstance(raw_vms, dict) and raw_vms:
        for vm_cfg in raw_vms.values():
            if not isinstance(vm_cfg, dict):
                continue
            raw_ifaces = vm_cfg.get("interfaces")
            if not isinstance(raw_ifaces, list):
                continue
            for nic in raw_ifaces:
                if not isinstance(nic, dict):
                    continue
                bridge = str(nic.get("bridge") or "").strip()
                if bridge:
                    bridges.add(bridge)
    else:
        raw_ifaces = inputs.get("interfaces")
        if isinstance(raw_ifaces, list):
            for nic in raw_ifaces:
                if not isinstance(nic, dict):
                    continue
                bridge = str(nic.get("bridge") or "").strip()
                if bridge:
                    bridges.add(bridge)
        vm_bridge = str(inputs.get("vm_bridge") or "").strip()
        if vm_bridge:
            bridges.add(vm_bridge)
    return bridges


def _resolve_sdn_expected_gateways(
    *,
    sdn_outputs: dict[str, Any],
    bridges: list[str],
) -> tuple[dict[str, set[str]], str]:
    subnets = sdn_outputs.get("subnets")
    if not isinstance(subnets, dict):
        return {}, "network_sdn outputs missing subnets"

    expected: dict[str, set[str]] = {bridge: set() for bridge in bridges}
    for subnet in subnets.values():
        if not isinstance(subnet, dict):
            continue
        bridge = str(subnet.get("vnet") or "").strip()
        if bridge not in expected:
            continue
        cidr = str(subnet.get("cidr") or "").strip()
        gateway = str(subnet.get("gateway") or "").strip()
        if not cidr or not gateway:
            continue
        try:
            network = ipaddress.ip_network(cidr, strict=True)
            gateway_ip = ipaddress.ip_address(gateway)
        except Exception:
            continue
        if not isinstance(network, ipaddress.IPv4Network) or not isinstance(gateway_ip, ipaddress.IPv4Address):
            continue
        if gateway_ip not in network:
            continue
        expected[bridge].add(f"{gateway_ip}/{int(network.prefixlen)}")

    missing = [bridge for bridge, addrs in expected.items() if not addrs]
    if missing:
        return {}, (
            "network_sdn outputs do not define expected gateway CIDRs for requested bridge(s): "
            f"[{', '.join(sorted(missing))}]"
        )

    return expected, ""


def _probe_proxmox_host_bridge_ipv4(
    *,
    host: str,
    user: str,
    key_file: str,
    bridges: list[str],
    timeout_s: int = 8,
) -> tuple[dict[str, set[str]], str]:
    ssh_bin = shutil.which("ssh")
    if not ssh_bin:
        return {}, "missing command: ssh"
    host = str(host or "").strip()
    user = str(user or "").strip() or "root"
    if not host:
        return {}, "missing proxmox ssh host"

    key_token = str(key_file or "").strip()
    resolved_key = ""
    if key_token:
        key_path = Path(key_token).expanduser()
        if not key_path.is_file():
            return {}, f"proxmox ssh key not found: {key_path}"
        resolved_key = str(key_path.resolve())

    cmd = [
        ssh_bin,
        "-o",
        "BatchMode=yes",
        "-o",
        "StrictHostKeyChecking=no",
        "-o",
        "UserKnownHostsFile=/dev/null",
        "-o",
        "ConnectTimeout=5",
        "-o",
        "LogLevel=ERROR",
    ]
    if resolved_key:
        cmd.extend(["-i", resolved_key, "-o", "IdentitiesOnly=yes"])
    cmd.append(f"{user}@{host}")
    quoted_bridges = " ".join(shlex.quote(bridge) for bridge in bridges)
    remote_cmd = (
        "for dev in "
        + quoted_bridges
        + "; do "
        + 'printf "__HYOPS_BRIDGE__ %s\\n" "$dev"; '
        + 'ip -4 -o addr show dev "$dev" 2>/dev/null || true; '
        + "done"
    )
    cmd.append(remote_cmd)

    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=max(2, int(timeout_s)),
        )
    except subprocess.TimeoutExpired as exc:
        return {}, f"proxmox ssh probe timed out after {exc.timeout}s"
    except Exception as exc:
        return {}, f"proxmox ssh probe failed: {exc}"

    if int(proc.returncode) != 0:
        detail = (proc.stderr or "").strip() or (proc.stdout or "").strip() or f"rc={proc.returncode}"
        return {}, f"proxmox ssh probe failed: {detail}"

    observed: dict[str, set[str]] = {bridge: set() for bridge in bridges}
    current_bridge = ""
    for raw_line in (proc.stdout or "").splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if line.startswith("__HYOPS_BRIDGE__ "):
            current_bridge = line.split(" ", 1)[1].strip()
            if current_bridge not in observed:
                observed[current_bridge] = set()
            continue
        if not current_bridge:
            continue
        match = re.search(r"\binet\s+([0-9.]+/\d+)\b", line)
        if match:
            observed.setdefault(current_bridge, set()).add(match.group(1))

    return observed, ""


def _probe_proxmox_vm_exists(
    *,
    api_url: str,
    api_token_id: str,
    api_token_secret: str,
    api_skip_tls: bool,
    node: str,
    host: str,
    user: str,
    key_file: str,
    vm_id: int,
    timeout_s: int = 8,
) -> tuple[bool, bool, str]:
    api_url = str(api_url or "").strip()
    api_token_id = str(api_token_id or "").strip()
    api_token_secret = str(api_token_secret or "").strip()
    node = str(node or "").strip()
    api_probe_err = ""
    if api_url and api_token_id and api_token_secret and node:
        base = api_url.rstrip("/")
        endpoint = f"{base}/nodes/{node}/qemu/{int(vm_id)}/config"
        req = urlrequest.Request(
            endpoint,
            headers={
                "Authorization": f"PVEAPIToken={api_token_id}={api_token_secret}",
                "Accept": "application/json",
            },
        )
        context = None
        if api_skip_tls:
            context = ssl.create_default_context()
            context.check_hostname = False
            context.verify_mode = ssl.CERT_NONE
        try:
            with urlrequest.urlopen(req, timeout=max(2, int(timeout_s)), context=context) as resp:
                payload = json.loads(resp.read().decode("utf-8") or "{}")
            data = payload.get("data")
            if not isinstance(data, dict):
                return False, False, f"proxmox api probe returned unexpected payload for vm_id={vm_id}"
            is_template = str(data.get("template") or "").strip() in ("1", "true", "True")
            return True, is_template, ""
        except urlerror.HTTPError as exc:
            body = ""
            try:
                body = exc.read().decode("utf-8", errors="replace").strip()
            except Exception:
                body = ""
            if int(exc.code) == 404:
                return False, False, ""
            detail = body or str(exc.reason or exc)
            api_probe_err = f"proxmox api probe failed: HTTP {exc.code}: {detail}"
        except Exception as exc:
            api_probe_err = f"proxmox api probe failed: {exc}"

    ssh_bin = shutil.which("ssh")
    if not ssh_bin:
        return False, False, api_probe_err or "missing command: ssh"
    host = str(host or "").strip()
    user = str(user or "").strip() or "root"
    if not host:
        return False, False, api_probe_err or "missing proxmox ssh host"

    key_token = str(key_file or "").strip()
    resolved_key = ""
    if key_token:
        key_path = Path(key_token).expanduser()
        if not key_path.is_file():
            return False, False, api_probe_err or f"proxmox ssh key not found: {key_path}"
        resolved_key = str(key_path.resolve())

    cmd = [
        ssh_bin,
        "-o",
        "BatchMode=yes",
        "-o",
        "StrictHostKeyChecking=no",
        "-o",
        "UserKnownHostsFile=/dev/null",
        "-o",
        "ConnectTimeout=5",
        "-o",
        "LogLevel=ERROR",
    ]
    if resolved_key:
        cmd.extend(["-i", resolved_key, "-o", "IdentitiesOnly=yes"])
    cmd.append(f"{user}@{host}")
    cmd.append(f"qm config {int(vm_id)}")

    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=max(2, int(timeout_s)),
        )
    except subprocess.TimeoutExpired as exc:
        return False, False, api_probe_err or f"proxmox vm probe timed out after {exc.timeout}s"
    except Exception as exc:
        return False, False, api_probe_err or f"proxmox vm probe failed: {exc}"

    if int(proc.returncode) != 0:
        detail = ((proc.stderr or "") + "\n" + (proc.stdout or "")).strip()
        lowered = detail.lower()
        if (
            "does not exist" in lowered
            or "not exist" in lowered
            or "no such file" in lowered
            or "configuration file" in lowered
        ):
            return False, False, ""
        return False, False, api_probe_err or f"proxmox vm probe failed: {detail or f'rc={proc.returncode}'}"

    config_text = proc.stdout or ""
    is_template = bool(re.search(r"(?m)^template:\s*1\s*$", config_text))
    return True, is_template, ""


def _infer_proxmox_jump_host(meta_dir: Path) -> str:
    """Best-effort infer a bastion host (Proxmox) for mgmt-only networks."""
    path = (meta_dir / "proxmox.ready.json").resolve()
    if not path.exists():
        return ""
    try:
        payload = json.loads(path.read_text(encoding="utf-8")) or {}
    except Exception:
        return ""
    runtime = payload.get("runtime")
    if not isinstance(runtime, dict):
        return ""
    return str(runtime.get("api_ip") or "").strip()


def _resolve_proxmox_runtime_credentials(credential_env: dict[str, str]) -> dict[str, Any]:
    """Resolve effective Proxmox credentials from runtime exports and tfvars files."""
    resolved: dict[str, Any] = {}
    candidate_paths: list[Path] = []

    for env_key in ("HYOPS_PROXMOX_TFVARS", "HYOPS_PROXMOX_CREDENTIALS_FILE"):
        raw = str(credential_env.get(env_key) or "").strip()
        if not raw:
            continue
        path = Path(raw).expanduser()
        if path in candidate_paths:
            continue
        candidate_paths.append(path)

    for path in candidate_paths:
        try:
            parsed = parse_tfvars(path.resolve())
        except Exception:
            continue
        for key, value in parsed.items():
            if key not in resolved and str(value).strip():
                resolved[key] = str(value).strip()

    for key in (
        "proxmox_url",
        "proxmox_token_id",
        "proxmox_token_secret",
        "proxmox_skip_tls",
        "proxmox_node",
        "proxmox_ssh_username",
        "proxmox_ssh_key",
    ):
        direct = credential_env.get(key)
        if direct is None:
            continue
        if key not in resolved and str(direct).strip():
            resolved[key] = direct

    if "proxmox_skip_tls" in resolved:
        resolved["proxmox_skip_tls"] = as_bool(resolved.get("proxmox_skip_tls"), default=False)

    return resolved


def _probe_netbox_api(base_url: str, token: str, *, timeout_s: float = 5.0) -> str:
    """Return empty string on success, otherwise an error message."""
    try:
        import requests  # type: ignore
    except ModuleNotFoundError:
        return "python dependency missing: requests (install via: hyops setup base --sudo)"

    url = base_url.rstrip("/") + "/api/dcim/sites/?limit=1"
    try:
        resp = requests.get(
            url,
            headers={"Authorization": f"Token {token}", "Accept": "application/json"},
            timeout=timeout_s,
        )
    except requests.RequestException as exc:  # type: ignore[attr-defined]
        return str(exc)

    if resp.status_code in (401, 403):
        return "NETBOX_API_TOKEN is rejected by NetBox API"
    if resp.status_code < 200 or resp.status_code >= 300:
        return f"HTTP {resp.status_code}"
    return ""


def _probe_netbox_api_with_retry(
    base_url: str,
    token: str,
    *,
    timeout_s: float = 5.0,
    wait_s: float = 30.0,
    interval_s: float = 2.0,
) -> tuple[str, float]:
    """Return (error, elapsed_s). Empty error means success."""
    try:
        total_wait = max(float(wait_s), 0.0)
    except Exception:
        total_wait = 30.0
    try:
        step = max(float(interval_s), 0.2)
    except Exception:
        step = 2.0

    start = time.time()
    deadline = start + total_wait
    last_err = ""

    while True:
        last_err = _probe_netbox_api(base_url, token, timeout_s=timeout_s)
        if not last_err:
            return "", max(0.0, time.time() - start)

        lower = last_err.lower()
        # These are not transient and should fail immediately.
        if "token is rejected" in lower or "python dependency missing" in lower:
            return last_err, max(0.0, time.time() - start)

        now = time.time()
        if now >= deadline:
            return last_err, max(0.0, now - start)

        time.sleep(min(step, max(0.0, deadline - now)))


def _pick_free_local_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _start_ssh_tunnel(
    *,
    jump_host: str,
    jump_user: str,
    jump_key_file: str,
    remote_host: str,
    remote_port: int,
) -> tuple[subprocess.Popen[str], str, str]:
    """Start an SSH local port-forward tunnel. Returns (proc, base_url, error)."""
    jump_host = jump_host.strip()
    jump_user = jump_user.strip() or "root"
    jump_key_file = str(Path(jump_key_file).expanduser()) if jump_key_file else ""
    remote_host = remote_host.strip()
    if not jump_host or not remote_host:
        return None, "", "ssh tunnel requires jump_host and remote_host"
    if remote_port <= 0:
        return None, "", "ssh tunnel requires a positive remote_port"

    local_port = _pick_free_local_port()
    forward = f"127.0.0.1:{local_port}:{remote_host}:{remote_port}"

    cmd = [
        "ssh",
        "-N",
        "-o",
        "ExitOnForwardFailure=yes",
        "-o",
        "ConnectTimeout=5",
        "-o",
        "ServerAliveInterval=30",
        "-o",
        "StrictHostKeyChecking=no",
        "-o",
        "UserKnownHostsFile=/dev/null",
        "-L",
        forward,
    ]
    if jump_key_file:
        cmd += ["-i", jump_key_file]
    cmd.append(f"{jump_user}@{jump_host}")

    try:
        proc: subprocess.Popen[str] = subprocess.Popen(
            cmd,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
    except Exception as exc:
        return None, "", f"failed to start ssh tunnel: {exc}"

    deadline = time.time() + 2.0
    while time.time() < deadline:
        if proc.poll() is not None:
            stderr = (proc.stderr.read() if proc.stderr else "") if proc.returncode else ""
            detail = stderr.strip().splitlines()
            msg = detail[0] if detail else f"rc={proc.returncode}"
            return None, "", f"ssh tunnel exited early: {msg}"
        try:
            with socket.create_connection(("127.0.0.1", local_port), timeout=0.2):
                return proc, f"http://127.0.0.1:{local_port}", ""
        except OSError:
            time.sleep(0.05)

    proc.terminate()
    try:
        proc.wait(timeout=2.0)
    except Exception:
        proc.kill()
    return None, "", "ssh tunnel did not become ready"


def _compute_static_pool(
    *,
    cidr: str,
    gateway: str,
    dhcp_start: str,
) -> tuple[ipaddress.IPv4Address, ipaddress.IPv4Address, int, str]:
    net = ipaddress.ip_network(cidr, strict=True)
    if not isinstance(net, ipaddress.IPv4Network):
        raise ValueError("subnet cidr must be IPv4")

    gw_ip = ipaddress.ip_address(gateway)
    dhcp_start_ip = ipaddress.ip_address(dhcp_start)
    if not isinstance(gw_ip, ipaddress.IPv4Address) or not isinstance(dhcp_start_ip, ipaddress.IPv4Address):
        raise ValueError("gateway/dhcp_start must be IPv4")
    if gw_ip not in net:
        raise ValueError(f"gateway {gateway} not inside prefix {cidr}")
    if dhcp_start_ip not in net:
        raise ValueError(f"dhcp_range_start {dhcp_start} not inside prefix {cidr}")

    start_int = int(gw_ip) + 1
    end_int = int(dhcp_start_ip) - 1
    if start_int > end_int:
        raise ValueError(f"invalid static pool for {cidr}: start>end")

    start_ip = ipaddress.ip_address(start_int)
    end_ip = ipaddress.ip_address(end_int)
    if not isinstance(start_ip, ipaddress.IPv4Address) or not isinstance(end_ip, ipaddress.IPv4Address):
        raise ValueError("computed static pool must be IPv4")
    if start_ip not in net or end_ip not in net:
        raise ValueError(f"computed static pool outside prefix {cidr}")

    return start_ip, end_ip, int(net.prefixlen), str(gw_ip)


def _collect_used_ipv4_hosts_from_platform_vm_state(state_dir: Path) -> set[str]:
    used: set[str] = set()
    try:
        payload = read_module_state(state_dir, "platform/onprem/platform-vm")
    except Exception:
        return used

    if str(payload.get("status") or "").strip().lower() != "ok":
        return used

    outputs = payload.get("outputs")
    if not isinstance(outputs, dict):
        return used

    vms = outputs.get("vms")
    if not isinstance(vms, dict):
        return used

    for _, vm in vms.items():
        if not isinstance(vm, dict):
            continue
        ifaces = vm.get("interfaces_configured")
        if not isinstance(ifaces, list):
            continue
        for nic in ifaces:
            if not isinstance(nic, dict):
                continue
            ipv4 = nic.get("ipv4")
            if not isinstance(ipv4, dict):
                continue
            addr = str(ipv4.get("address") or "").strip()
            if not addr:
                continue
            try:
                iface = ipaddress.ip_interface(addr)
            except Exception:
                continue
            if isinstance(iface, ipaddress.IPv4Interface):
                used.add(str(iface.ip))
    return used


def _collect_requested_vm_names(inputs: dict[str, Any]) -> set[str]:
    names: set[str] = set()
    raw_vms = inputs.get("vms")
    if isinstance(raw_vms, dict) and raw_vms:
        for raw_name in raw_vms.keys():
            name = str(raw_name).strip()
            if name:
                names.add(name)
        return names

    vm_name = str(inputs.get("vm_name") or "").strip()
    if vm_name:
        names.add(vm_name)
    return names


def _extract_vm_names_from_outputs(outputs: dict[str, Any]) -> set[str]:
    out: set[str] = set()
    raw_vms = outputs.get("vms")
    if isinstance(raw_vms, dict):
        for raw_name in raw_vms.keys():
            name = str(raw_name).strip()
            if name:
                out.add(name)

    if out:
        return out

    raw_vm_names = outputs.get("vm_names")
    if isinstance(raw_vm_names, list):
        for item in raw_vm_names:
            name = str(item).strip()
            if name:
                out.add(name)
    return out


def _extract_vm_names_from_state_payload(payload: Any) -> set[str]:
    if not isinstance(payload, dict):
        return set()
    if str(payload.get("status") or "").strip().lower() != "ok":
        return set()
    outputs = payload.get("outputs")
    if not isinstance(outputs, dict):
        return set()
    return _extract_vm_names_from_outputs(outputs)


def _collect_existing_managed_vm_names_by_slot(
    state_dir: Path,
    module_ref: str,
) -> tuple[dict[str, set[str]], str]:
    module_id = module_id_from_ref(module_ref)
    if not module_id:
        return {}, f"invalid module_ref for collision check: {module_ref!r}"

    module_dir = (state_dir / "modules" / module_id).resolve()
    if not module_dir.exists():
        return {}, ""

    out: dict[str, set[str]] = {}

    latest_path = module_dir / "latest.json"
    if latest_path.exists():
        try:
            latest_payload = read_json(latest_path)
        except Exception as exc:
            return {}, f"failed to read existing module state for collision check: {exc}"
        latest_names = _extract_vm_names_from_state_payload(latest_payload)
        if latest_names:
            out["latest"] = latest_names

    instances_dir = module_dir / "instances"
    if instances_dir.exists():
        try:
            instance_paths = sorted(instances_dir.glob("*.json"))
        except Exception as exc:
            return {}, f"failed to enumerate instance states for collision check: {exc}"
        for path in instance_paths:
            try:
                payload = read_json(path)
            except Exception as exc:
                return {}, f"failed to read instance state for collision check: {path} ({exc})"
            names = _extract_vm_names_from_state_payload(payload)
            if names:
                out[f"instance:{path.stem}"] = names

    return out, ""


def _format_vm_set_diff(existing: set[str], requested: set[str]) -> str:
    existing_only = sorted(existing - requested)
    requested_only = sorted(requested - existing)
    return f"existing_only={existing_only}, requested_only={requested_only}"


def _ensure_netbox_client(
    *,
    env: dict[str, str],
    runtime_root: Path,
    meta_dir: Path,
    credential_env: dict[str, str],
    ssh_proxy_jump_host: str = "",
    ssh_proxy_jump_user: str = "",
    ssh_proxy_jump_key_file: str = "",
) -> tuple[Any, str, list[str], str]:
    """Return (client, base_url, warnings, error)."""
    from hyops.runtime.netbox_env import hydrate_netbox_env

    warnings: list[str] = []
    hydrate_warnings, missing = hydrate_netbox_env(env, runtime_root)
    warnings.extend(hydrate_warnings)
    if missing:
        missing_str = ", ".join(missing)
        env_name = str(env.get("HYOPS_ENV") or "").strip() or "<env>"
        hint = f"inputs.addressing.mode=ipam requires {missing_str}. "
        hint += f"Run: hyops secrets ensure --env {env_name} NETBOX_API_TOKEN (and ensure NETBOX_API_URL is set via NetBox state or credentials/netbox.env)."
        return None, "", warnings, hint

    base_url = str(env.get("NETBOX_API_URL") or "").strip().rstrip("/")
    token = str(env.get("NETBOX_API_TOKEN") or "").strip()
    try:
        probe_wait_s = float(str(env.get("HYOPS_NETBOX_API_PROBE_WAIT_S") or "30").strip())
    except Exception:
        probe_wait_s = 30.0

    # Probe direct reachability first.
    err, direct_elapsed = _probe_netbox_api_with_retry(
        base_url,
        token,
        timeout_s=5.0,
        wait_s=probe_wait_s,
        interval_s=2.0,
    )
    if not err and direct_elapsed > 1.0:
        warnings.append(f"netbox api became ready after retry wait ({direct_elapsed:.1f}s)")
    if err:
        # Optional: tunnel via Proxmox (typical in lab setups where mgmt is not routed).
        proxmox_credentials = _resolve_proxmox_runtime_credentials(credential_env)
        jump_host = str(ssh_proxy_jump_host or "").strip() or _infer_proxmox_jump_host(meta_dir)
        jump_user = (
            str(ssh_proxy_jump_user or "").strip()
            or str(proxmox_credentials.get("proxmox_ssh_username") or "root").strip()
            or "root"
        )
        jump_key = (
            str(ssh_proxy_jump_key_file or "").strip()
            or str(proxmox_credentials.get("proxmox_ssh_key") or "~/.ssh/id_ed25519").strip()
            or "~/.ssh/id_ed25519"
        )

        parsed = urlparse(base_url)
        remote_host = parsed.hostname or ""
        remote_port = int(parsed.port or (443 if parsed.scheme == "https" else 80))
        if jump_host and remote_host:
            proc, tunneled_base_url, tunnel_err = _start_ssh_tunnel(
                jump_host=jump_host,
                jump_user=jump_user,
                jump_key_file=jump_key,
                remote_host=remote_host,
                remote_port=remote_port,
            )
            if tunnel_err:
                return None, "", warnings, f"NetBox API unreachable ({err}); ssh tunnel failed: {tunnel_err}"

            # Probe via tunnel, then terminate the tunnel (we only need it for API calls in this contract).
            tunnel_probe_err, tunnel_elapsed = _probe_netbox_api_with_retry(
                tunneled_base_url,
                token,
                timeout_s=5.0,
                wait_s=probe_wait_s,
                interval_s=2.0,
            )
            if tunnel_probe_err:
                proc.terminate()
                try:
                    proc.wait(timeout=2.0)
                except Exception:
                    proc.kill()
                return None, "", warnings, f"NetBox API unreachable ({err}); tunnel probe failed: {tunnel_probe_err}"

            warnings.append(
                f"netbox api unreachable directly; using ssh tunnel via {jump_user}@{jump_host}"
            )
            if tunnel_elapsed > 1.0:
                warnings.append(f"netbox api tunnel became ready after retry wait ({tunnel_elapsed:.1f}s)")

            try:
                from hyops.drivers.inventory.netbox.tools.netbox_api import client_from
            except ModuleNotFoundError as exc:
                proc.terminate()
                try:
                    proc.wait(timeout=2.0)
                except Exception:
                    proc.kill()
                return None, "", warnings, f"ipam requires python dependency: {exc.name} (run: hyops setup base --sudo)"

            client = client_from(base_url=tunneled_base_url, token=token, dry_run=False)
            # Caller must terminate proc after use. We return it attached in a tuple.
            return (client, proc), tunneled_base_url, warnings, ""

        return None, "", warnings, (
            f"NetBox API unreachable: {err}. Ensure your workstation has L3 access to the management network, "
            "or configure a bastion/tunnel."
        )

    try:
        from hyops.drivers.inventory.netbox.tools.netbox_api import client_from
    except ModuleNotFoundError as exc:
        return None, "", warnings, f"ipam requires python dependency: {exc.name} (run: hyops setup base --sudo)"

    client = client_from(base_url=base_url, token=token, dry_run=False)
    return (client, None), base_url, warnings, ""


def _reserve_ip_for_interface(
    *,
    client: Any,
    prefixlen: int,
    start_ip: ipaddress.IPv4Address,
    end_ip: ipaddress.IPv4Address,
    used_hosts: set[str],
    description: str,
    tags: list[str],
) -> tuple[str, str]:
    """Return (cidr, error)."""
    try:
        from hyops.drivers.inventory.netbox.tools.netbox_api import (
            NetBoxConflictError,
            find_ip_by_description,
            reserve_ip,
        )
    except ModuleNotFoundError as exc:
        return "", f"ipam requires python dependency: {exc.name} (run: hyops setup base --sudo)"

    existing = None
    try:
        existing = find_ip_by_description(client, description=description)
    except Exception:
        existing = None
    if isinstance(existing, dict):
        addr = str(existing.get("address") or "").strip()
        if addr:
            return addr, ""

    for ip_int in range(int(start_ip), int(end_ip) + 1):
        host = str(ipaddress.ip_address(ip_int))
        if host in used_hosts:
            continue
        addr = f"{host}/{prefixlen}"
        try:
            _ = reserve_ip(client, address=addr, description=description, tags=tags, status="reserved")
        except NetBoxConflictError:
            used_hosts.add(host)
            continue
        except Exception as exc:
            return "", f"failed to reserve IP {addr}: {exc}"
        used_hosts.add(host)
        return addr, ""

    return "", "no available IPs in static pool"


class ProxmoxVmContract(TerragruntModuleContract):
    """
    Contract hook point for Proxmox VM-oriented modules.

    Current responsibilities:
    - state-first template resolution via template_state_ref/template_key
    - fast-fail gate for build_image until packer driver migration lands
    - module-specific preflight constraints for VM lifecycle operations
    """

    def preprocess_inputs(
        self,
        *,
        command_name: str,
        module_ref: str,
        inputs: dict[str, Any],
        profile_policy: dict[str, Any],
        runtime: dict[str, Any],
        env: dict[str, str],
        credential_env: dict[str, str],
    ) -> tuple[dict[str, Any], list[str], str]:
        normalized_command = str(command_name or "").strip().lower()
        lifecycle_command = str(runtime.get("lifecycle_command") or "").strip().lower()
        effective_command = (
            lifecycle_command
            if normalized_command == "preflight" and lifecycle_command
            else normalized_command
        )
        if effective_command not in ("apply", "deploy", "plan", "validate", "preflight"):
            return inputs, [], ""

        out = dict(inputs)
        warnings: list[str] = []
        env_name = str(env.get("HYOPS_ENV") or runtime.get("env") or "").strip()

        alias_warnings, alias_err = _resolve_bridge_aliases(out, env_name=env_name)
        warnings.extend(alias_warnings)
        if alias_err:
            return out, warnings, alias_err

        build_image = as_bool(out.get("build_image"), default=False)
        if build_image:
            return (
                out,
                warnings,
                "build_image=true is not supported yet for this module; build an image first and reference it via template_state_ref "
                "(try: template_state_ref=core/onprem/template-image, template_key=ubuntu-24.04)",
            )

        template_state_ref = str(out.get("template_state_ref") or "").strip()
        template_key = str(out.get("template_key") or "").strip()

        state_dir_raw = str(runtime.get("state_dir") or "").strip()
        if not state_dir_raw:
            return out, warnings, "runtime.state_dir is required"

        state_dir = Path(state_dir_raw).expanduser().resolve()
        if template_state_ref and as_positive_int(out.get("template_vm_id")) is None:
            try:
                state_payload = read_module_state(state_dir, template_state_ref)
            except FileNotFoundError:
                return (
                    out,
                    warnings,
                    f"template_state_ref not found in env state: {template_state_ref} "
                    "(run: hyops deploy --module core/onprem/template-image --inputs <inputs.yml>)",
                )
            except Exception as exc:
                return out, warnings, f"failed to read template_state_ref {template_state_ref}: {exc}"

            state_status = str(state_payload.get("status") or "").strip().lower()
            if state_status != "ok":
                return (
                    out,
                    warnings,
                    f"template_state_ref exists but is not ready: {template_state_ref} status={state_status or 'unknown'}",
                )

            outputs = state_payload.get("outputs")
            if not isinstance(outputs, dict):
                return (
                    out,
                    warnings,
                    f"template_state_ref has no usable outputs: {template_state_ref}",
                )

            template_id = _pick_template_id(outputs, template_key)
            if template_id is None:
                out_keys = ", ".join(sorted(outputs.keys()))
                key_msg = f" key={template_key}" if template_key else ""
                return (
                    out,
                    warnings,
                    f"unable to resolve template VM ID from template_state_ref={template_state_ref}{key_msg}; outputs keys: [{out_keys}]",
                )

            out["template_vm_id"] = int(template_id)
            warnings.append(
                f"resolved template_vm_id={template_id} from template_state_ref={template_state_ref}"
            )
        elif template_key and not template_state_ref:
            warnings.append("template_key ignored because template_state_ref is not set")

        resolved_template_vm_id = as_positive_int(out.get("template_vm_id"))
        if resolved_template_vm_id is not None:
            meta_dir = (
                Path(str(runtime.get("meta_dir") or "")).expanduser().resolve()
                if str(runtime.get("meta_dir") or "").strip()
                else None
            )
            proxmox_credentials = _resolve_proxmox_runtime_credentials(credential_env)
            proxmox_host = _infer_proxmox_jump_host(meta_dir) if meta_dir else ""
            proxmox_user = str(proxmox_credentials.get("proxmox_ssh_username") or "root").strip() or "root"
            proxmox_key = str(proxmox_credentials.get("proxmox_ssh_key") or "").strip()
            proxmox_api_url = str(proxmox_credentials.get("proxmox_url") or "").strip()
            proxmox_token_id = str(proxmox_credentials.get("proxmox_token_id") or "").strip()
            proxmox_token_secret = str(proxmox_credentials.get("proxmox_token_secret") or "").strip()
            proxmox_skip_tls = as_bool(proxmox_credentials.get("proxmox_skip_tls"), default=False)
            proxmox_node = str(proxmox_credentials.get("proxmox_node") or "").strip()
            if (proxmox_api_url and proxmox_token_id and proxmox_token_secret and proxmox_node) or (
                proxmox_host and proxmox_key
            ):
                exists, is_template, probe_err = _probe_proxmox_vm_exists(
                    api_url=proxmox_api_url,
                    api_token_id=proxmox_token_id,
                    api_token_secret=proxmox_token_secret,
                    api_skip_tls=proxmox_skip_tls,
                    node=proxmox_node,
                    host=proxmox_host,
                    user=proxmox_user,
                    key_file=proxmox_key,
                    vm_id=int(resolved_template_vm_id),
                )
                if probe_err:
                    warnings.append(f"template vm probe skipped: {probe_err}")
                elif not exists:
                    if template_state_ref:
                        source_hint = (
                            f"template_vm_id={resolved_template_vm_id} resolved from template_state_ref={template_state_ref}"
                        )
                    else:
                        source_hint = f"configured template_vm_id={resolved_template_vm_id}"
                    return (
                        out,
                        warnings,
                        f"{source_hint}, but no VM/template with that ID exists on the Proxmox host. "
                        "Rebuild or reseed the template first "
                        "(for example: core/onprem/template-image or core/onprem/vyos-template-seed).",
                    )
                elif not is_template:
                    return (
                        out,
                        warnings,
                        f"template_vm_id={resolved_template_vm_id} exists on the Proxmox host but is not marked as a template. "
                        "Fix the source VM or rebuild the template before continuing.",
                    )
            else:
                warnings.append(
                    "template vm probe skipped: proxmox API or SSH runtime credentials are not available"
                )

        # Hard safety rail: prevent accidental destructive replacement of an
        # already-managed VM set under the same module_ref in the same env.
        requested_vm_names = _collect_requested_vm_names(out)
        if requested_vm_names:
            raw_state_instance = str(runtime.get("state_instance") or "").strip().lower()
            current_slot = f"instance:{raw_state_instance}" if raw_state_instance else "latest"

            existing_by_slot, existing_err = _collect_existing_managed_vm_names_by_slot(
                state_dir, module_ref
            )
            if existing_err:
                return out, warnings, existing_err

            existing_vm_names = existing_by_slot.get(current_slot, set())
            if existing_vm_names and existing_vm_names != requested_vm_names:
                allow_replace = as_bool(out.get("allow_vm_set_replace"), default=False)
                diff = _format_vm_set_diff(existing_vm_names, requested_vm_names)
                if not allow_replace:
                    return (
                        out,
                        warnings,
                        "vm set collision detected: requested VM names differ from existing managed VM names "
                        f"for module_ref={module_ref}; {diff}. "
                        "This run would replace active VMs. Use a separate env/module scope, or explicitly set "
                        "inputs.allow_vm_set_replace=true when replacement is intentional.",
                    )
                warnings.append(
                    "allow_vm_set_replace=true: proceeding despite VM set collision "
                    f"for module_ref={module_ref}; {diff}"
                )

            # Guard against duplicated VM names across different state slots
            # (for example latest vs instance), which can silently create
            # duplicate Proxmox VMs with clashing IP/name intent.
            cross_slot_conflicts: list[str] = []
            for slot, names in existing_by_slot.items():
                if slot == current_slot:
                    continue
                overlap = sorted(names & requested_vm_names)
                if overlap:
                    cross_slot_conflicts.append(f"{slot} overlap={overlap}")
            if cross_slot_conflicts:
                detail = "; ".join(cross_slot_conflicts)
                return (
                    out,
                    warnings,
                    "vm name collision detected across module state slots "
                    f"for module_ref={module_ref}: requested={sorted(requested_vm_names)}; {detail}. "
                    "Use one slot consistently (latest or a single state_instance), or destroy the stale slot first.",
                )

        # Fail fast when a VM consumer targets HybridOps SDN bridges (vnet*) but the shared SDN
        # authority is missing/not ready. This applies to both IPAM and static-addressed runs.
        requested_bridges = _collect_requested_bridges(out)
        managed_sdn_bridges = sorted({b for b in requested_bridges if b.lower().startswith("vnet")})
        if managed_sdn_bridges:
            network_state_ref_for_bridges = "core/onprem/network-sdn"
            raw_addr = out.get("addressing")
            if isinstance(raw_addr, dict):
                raw_ipam = raw_addr.get("ipam")
                if isinstance(raw_ipam, dict):
                    network_state_ref_for_bridges = str(
                        raw_ipam.get("network_state_ref") or network_state_ref_for_bridges
                    ).strip()
            net_state_for_bridges, sdn_warnings, sdn_err = _read_network_sdn_state_with_authority(
                state_dir=state_dir,
                network_state_ref=network_state_ref_for_bridges,
            )
            warnings.extend(sdn_warnings)
            if sdn_err:
                return (
                    out,
                    warnings,
                    "managed bridge(s) require network_sdn state: "
                    f"{sdn_err}. Requested bridges: [{', '.join(managed_sdn_bridges)}]",
                )
            sdn_status = str(net_state_for_bridges.get("status") or "").strip().lower()
            if sdn_status != "ok":
                return (
                    out,
                    warnings,
                    "managed bridge(s) require network_sdn state status=ok: "
                    f"{network_state_ref_for_bridges} status={sdn_status or 'unknown'} "
                    f"(requested bridges: [{', '.join(managed_sdn_bridges)}])",
                )
            sdn_outputs = net_state_for_bridges.get("outputs")
            if not isinstance(sdn_outputs, dict):
                return out, warnings, f"network_sdn state has no outputs: {network_state_ref_for_bridges}"
            sdn_vnets = sdn_outputs.get("vnets")
            if not isinstance(sdn_vnets, dict):
                return out, warnings, f"network_sdn outputs missing vnets: {network_state_ref_for_bridges}"
            missing_bridges = [b for b in managed_sdn_bridges if b not in sdn_vnets]
            if missing_bridges:
                known = ", ".join(sorted(str(k) for k in sdn_vnets.keys()))
                return (
                    out,
                    warnings,
                    "requested HybridOps SDN bridge(s) are not present in network_sdn state outputs: "
                    f"[{', '.join(missing_bridges)}]. Known vnets: [{known}]",
                )
            expected_gateways, gateway_err = _resolve_sdn_expected_gateways(
                sdn_outputs=sdn_outputs,
                bridges=managed_sdn_bridges,
            )
            if gateway_err:
                return out, warnings, gateway_err

            meta_dir = Path(str(runtime.get("meta_dir") or "")).expanduser().resolve() if str(runtime.get("meta_dir") or "").strip() else None
            proxmox_credentials = _resolve_proxmox_runtime_credentials(credential_env)
            proxmox_host = _infer_proxmox_jump_host(meta_dir) if meta_dir else ""
            proxmox_user = str(proxmox_credentials.get("proxmox_ssh_username") or "root").strip() or "root"
            proxmox_key = str(proxmox_credentials.get("proxmox_ssh_key") or "").strip()
            if proxmox_host and proxmox_key:
                observed_gateways, probe_err = _probe_proxmox_host_bridge_ipv4(
                    host=proxmox_host,
                    user=proxmox_user,
                    key_file=proxmox_key,
                    bridges=managed_sdn_bridges,
                )
                if probe_err:
                    warnings.append(f"sdn host gateway probe skipped: {probe_err}")
                else:
                    drift: list[str] = []
                    for bridge in managed_sdn_bridges:
                        expected_for_bridge = sorted(expected_gateways.get(bridge) or [])
                        observed_for_bridge = sorted(observed_gateways.get(bridge) or [])
                        if any(addr in observed_for_bridge for addr in expected_for_bridge):
                            continue
                        drift.append(
                            f"{bridge} expected={expected_for_bridge} observed={observed_for_bridge}"
                        )
                    if drift:
                        env_name_hint = str(env.get("HYOPS_ENV") or runtime.get("env") or _DEFAULT_SDN_AUTHORITY_ENV).strip() or _DEFAULT_SDN_AUTHORITY_ENV
                        return (
                            out,
                            warnings,
                            "host-side Proxmox SDN gateway drift detected for requested HybridOps bridge(s): "
                            + "; ".join(drift)
                            + ". Re-run core/onprem/network-sdn with the same topology inputs and a fresh "
                            + "host_reconcile_nonce, for example: "
                            + f"HYOPS_INPUT_host_reconcile_nonce=$(date -u +%Y%m%dT%H%M%SZ) hyops apply --env {env_name_hint} "
                            + "--module core/onprem/network-sdn --inputs <network-sdn-inputs.yml>",
                        )
            else:
                if not proxmox_host:
                    warnings.append(
                        "sdn host gateway probe skipped: proxmox.ready.json is missing or does not publish api_ip"
                    )
                elif not proxmox_key:
                    warnings.append(
                        "sdn host gateway probe skipped: proxmox ssh key not available in runtime credentials"
                    )

        # Optional: IPAM-driven static addressing (NetBox authority).
        addressing = out.get("addressing")
        if isinstance(addressing, dict) and str(addressing.get("mode") or "").strip().lower() == "ipam":
            ipam = addressing.get("ipam")
            if not isinstance(ipam, dict):
                return out, warnings, "inputs.addressing.ipam must be a mapping when inputs.addressing.mode=ipam"
            provider = str(ipam.get("provider") or "").strip().lower()
            if provider != "netbox":
                return out, warnings, "inputs.addressing.ipam.provider must be 'netbox'"

            runtime_root_raw = str(runtime.get("root") or "").strip()
            meta_dir_raw = str(runtime.get("meta_dir") or "").strip()
            if not runtime_root_raw or not meta_dir_raw:
                return out, warnings, "runtime.root and runtime.meta_dir are required for ipam mode"
            runtime_root = Path(runtime_root_raw).expanduser().resolve()
            meta_dir = Path(meta_dir_raw).expanduser().resolve()

            _, netbox_err = _netbox_ready(state_dir)
            if netbox_err:
                return out, warnings, f"ipam requires netbox ready: {netbox_err}"

            # Preflight/plan/validate must not reserve addresses; only probe readiness.
            (client_and_proc, base_url, nb_warnings, nb_err) = _ensure_netbox_client(
                env=env,
                runtime_root=runtime_root,
                meta_dir=meta_dir,
                credential_env=credential_env,
                ssh_proxy_jump_host=str(ipam.get("ssh_proxy_jump_host") or "").strip(),
                ssh_proxy_jump_user=str(ipam.get("ssh_proxy_jump_user") or "").strip(),
                ssh_proxy_jump_key_file=str(ipam.get("ssh_proxy_jump_key_file") or "").strip(),
            )
            warnings.extend(nb_warnings)
            if nb_err:
                return out, warnings, nb_err

            # client_and_proc is (client, proc|None). We'll terminate proc at the end.
            (client, proc) = client_and_proc

            try:
                network_state_ref = str(ipam.get("network_state_ref") or "core/onprem/network-sdn").strip()
                net_state, sdn_warnings, sdn_err = _read_network_sdn_state_with_authority(
                    state_dir=state_dir,
                    network_state_ref=network_state_ref,
                )
                warnings.extend(sdn_warnings)
                if sdn_err:
                    return out, warnings, f"ipam requires network_sdn state: {sdn_err}"
                if str(net_state.get("status") or "").strip().lower() != "ok":
                    st = str(net_state.get("status") or "").strip().lower() or "missing"
                    return out, warnings, f"ipam requires network_sdn state ok: {network_state_ref} status={st}"

                outputs = net_state.get("outputs")
                if not isinstance(outputs, dict):
                    return out, warnings, f"ipam requires network_sdn outputs: {network_state_ref}"
                vnets = outputs.get("vnets")
                subnets = outputs.get("subnets")
                zone_name = str(outputs.get("zone_name") or "").strip() or "onprem"
                if not isinstance(vnets, dict) or not isinstance(subnets, dict):
                    return out, warnings, f"ipam requires vnets/subnets in state outputs: {network_state_ref}"

                subnet_by_vnet: dict[str, dict[str, Any]] = {}
                for _, s in subnets.items():
                    if not isinstance(s, dict):
                        continue
                    vnet_name = str(s.get("vnet") or "").strip()
                    if vnet_name and vnet_name not in subnet_by_vnet:
                        subnet_by_vnet[vnet_name] = s

                used_hosts = _collect_used_ipv4_hosts_from_platform_vm_state(state_dir)

                # No mutations on preflight/plan/validate: we just prove we can reach NetBox and parse pools.
                if normalized_command in ("preflight", "plan", "validate"):
                    return out, warnings, ""

                try:
                    from hyops.drivers.inventory.netbox.tools.netbox_api import (
                        ensure_ip_range,
                        ensure_ipam_role,
                        ensure_prefix,
                        ensure_site,
                        ensure_vlan,
                    )
                except ModuleNotFoundError as exc:
                    return out, warnings, f"ipam requires python dependency: {exc.name} (run: hyops setup base --sudo)"

                site = ensure_site(client, zone_name)
                role = ensure_ipam_role(client, "hyops-static")

                # NetBox API may require pre-existing tag objects when tags are
                # provided by attribute payload. Keep IP reservations tagless
                # unless explicit tag lifecycle management is introduced.
                tags: list[str] = []

                def apply_ipam_to_interfaces(vm_name: str, interfaces: list[Any]) -> str:
                    for idx, nic_raw in enumerate(interfaces):
                        if not isinstance(nic_raw, dict):
                            return f"inputs.vms[{vm_name}].interfaces[{idx+1}] must be a mapping"
                        bridge = str(nic_raw.get("bridge") or "").strip()
                        if not bridge:
                            return f"inputs.vms[{vm_name}].interfaces[{idx+1}].bridge is required"

                        ipv4 = nic_raw.get("ipv4")
                        needs_alloc = True
                        if isinstance(ipv4, dict):
                            addr = str(ipv4.get("address") or "").strip().lower()
                            if addr and addr != "dhcp":
                                needs_alloc = False
                        elif ipv4 is None:
                            needs_alloc = True
                        else:
                            return f"inputs.vms[{vm_name}].interfaces[{idx+1}].ipv4 must be a mapping when set"

                        if not needs_alloc:
                            continue

                        subnet = subnet_by_vnet.get(bridge)
                        if not subnet:
                            known = ", ".join(sorted(subnet_by_vnet.keys()))
                            return (
                                f"ipam cannot map bridge={bridge!r} to a subnet from {network_state_ref}. "
                                f"Known vnets: [{known}]"
                            )

                        cidr = str(subnet.get("cidr") or "").strip()
                        gateway = str(subnet.get("gateway") or "").strip()
                        dhcp_start = str(subnet.get("dhcp_range_start") or "").strip()
                        if not cidr or not gateway or not dhcp_start:
                            return f"ipam requires cidr/gateway/dhcp_range_start in subnet for bridge={bridge}"

                        start_ip, end_ip, prefixlen, gw = _compute_static_pool(
                            cidr=cidr,
                            gateway=gateway,
                            dhcp_start=dhcp_start,
                        )

                        vnet = vnets.get(bridge) if isinstance(vnets.get(bridge), dict) else {}
                        vlan_id = int(vnet.get("vlan_id") or 0) if isinstance(vnet, dict) else 0
                        vlan_obj = None
                        if vlan_id > 0:
                            vlan_obj = ensure_vlan(
                                client,
                                vid=vlan_id,
                                site_id=int(site["id"]),
                                name=bridge,
                                role_id=int(role["id"]),
                            )

                        ensure_prefix(
                            client,
                            prefix=cidr,
                            site_id=int(site["id"]),
                            vlan_id=int(vlan_obj["id"]) if isinstance(vlan_obj, dict) else None,
                            role_id=int(role["id"]),
                            status="active",
                            description=f"hyops {zone_name} {bridge}",
                        )
                        ensure_ip_range(
                            client,
                            start_address=str(start_ip),
                            end_address=str(end_ip),
                            role_id=int(role["id"]),
                            status="active",
                            description=f"hyops static pool {zone_name} {bridge}",
                        )

                        desc = f"hyops:{zone_name}:{vm_name}:{bridge}:{idx+1}"
                        reserved_cidr, alloc_err = _reserve_ip_for_interface(
                            client=client,
                            prefixlen=prefixlen,
                            start_ip=start_ip,
                            end_ip=end_ip,
                            used_hosts=used_hosts,
                            description=desc,
                            tags=tags,
                        )
                        if alloc_err:
                            return f"ipam allocation failed for {vm_name} {bridge}: {alloc_err}"

                        if not isinstance(ipv4, dict):
                            ipv4 = {}
                            nic_raw["ipv4"] = ipv4
                        ipv4["address"] = reserved_cidr
                        if idx == 0:
                            ipv4["gateway"] = gw
                        else:
                            ipv4.pop("gateway", None)

                    return ""

                vms = out.get("vms")
                is_pool = isinstance(vms, dict) and len(vms) > 0

                if is_pool:
                    module_ifaces = out.get("interfaces")
                    module_ifaces_list: list[Any] = module_ifaces if isinstance(module_ifaces, list) else []

                    for vm_name, vm_cfg in vms.items():
                        if not isinstance(vm_cfg, dict):
                            return out, warnings, f"inputs.vms[{vm_name}] must be a mapping"

                        ifaces = vm_cfg.get("interfaces")
                        if ifaces is None:
                            if not module_ifaces_list:
                                return (
                                    out,
                                    warnings,
                                    f"ipam requires inputs.vms[{vm_name}].interfaces (or module-level inputs.interfaces) "
                                    "so HybridOps can map bridge->subnet for allocation",
                                )
                            # module-level interfaces are templates; copy per-VM before allocation.
                            ifaces = copy.deepcopy(module_ifaces_list)
                            vm_cfg["interfaces"] = ifaces

                        if not isinstance(ifaces, list) or not ifaces:
                            return out, warnings, f"inputs.vms[{vm_name}].interfaces must be a non-empty list"

                        err = apply_ipam_to_interfaces(str(vm_name), ifaces)
                        if err:
                            return out, warnings, err
                else:
                    ifaces = out.get("interfaces")
                    if not isinstance(ifaces, list) or not ifaces:
                        return (
                            out,
                            warnings,
                            "ipam requires inputs.interfaces (single-VM) or inputs.vms.<name>.interfaces (pool) "
                            "so HybridOps can map bridge->subnet for allocation",
                        )
                    err = apply_ipam_to_interfaces(str(out.get("vm_name") or "vm"), ifaces)
                    if err:
                        return out, warnings, err

            finally:
                if proc is not None:
                    proc.terminate()
                    try:
                        proc.wait(timeout=2.0)
                    except Exception:
                        proc.kill()

        return out, warnings, ""
