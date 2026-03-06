"""
purpose: Post-apply readiness checks for terragrunt-managed modules.
Architecture Decision: ADR-N/A (terragrunt post-apply readiness)
maintainer: HybridOps.Studio
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
import ipaddress
import shutil
import time

from hyops.drivers.config.ansible.connectivity import (
    apply_proxy_jump_auto,
    connectivity_check,
    resolve_default_bastion,
)
from hyops.runtime.coerce import as_bool, as_int
from hyops.runtime.proc import run_capture


def _as_mapping(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return dict(value)
    return {}


def _iter_strings(value: Any) -> list[str]:
    out: list[str] = []
    if isinstance(value, str):
        token = value.strip()
        if token:
            out.append(token)
        return out
    if isinstance(value, list):
        for item in value:
            out.extend(_iter_strings(item))
    return out


def _coerce_ipv4_host(raw: str) -> str:
    token = str(raw or "").strip()
    if not token:
        return ""
    if token.lower() == "dhcp":
        return ""
    try:
        if "/" in token:
            iface = ipaddress.ip_interface(token)
            if isinstance(iface, ipaddress.IPv4Interface):
                return str(iface.ip)
            return ""
        addr = ipaddress.ip_address(token)
        if isinstance(addr, ipaddress.IPv4Address):
            return str(addr)
        return ""
    except Exception:
        return ""


def _pick_vm_ipv4_host(vm: dict[str, Any]) -> str:
    direct = _coerce_ipv4_host(str(vm.get("ipv4_address") or ""))
    if direct:
        return direct

    configured = _coerce_ipv4_host(str(vm.get("ipv4_configured_primary") or ""))
    if configured:
        return configured

    for candidate in _iter_strings(vm.get("ipv4_addresses")):
        ip = _coerce_ipv4_host(candidate)
        if ip and not ip.startswith("127."):
            return ip

    for item in vm.get("interfaces_configured") or []:
        if not isinstance(item, dict):
            continue
        ipv4 = item.get("ipv4")
        if not isinstance(ipv4, dict):
            continue
        ip = _coerce_ipv4_host(str(ipv4.get("address") or ""))
        if ip and not ip.startswith("127."):
            return ip

    return ""


def _collect_platform_vm_targets(outputs: dict[str, Any]) -> tuple[list[dict[str, str]], list[str]]:
    targets: list[dict[str, str]] = []
    warnings: list[str] = []

    raw_vms = outputs.get("vms")
    if not isinstance(raw_vms, dict):
        warnings.append("post-apply SSH readiness skipped: outputs.vms is missing or not a map")
        return targets, warnings

    for raw_name, raw_vm in raw_vms.items():
        name = str(raw_name or "").strip() or "vm"
        vm = raw_vm if isinstance(raw_vm, dict) else {}
        if as_bool(vm.get("is_windows"), default=False):
            warnings.append(f"post-apply SSH readiness skipped windows VM: {name}")
            continue
        host = _pick_vm_ipv4_host(vm)
        if not host:
            warnings.append(
                f"post-apply SSH readiness skipped VM with no IPv4 host in outputs.vms: {name}"
            )
            continue
        targets.append({"name": name, "host": host})

    return targets, warnings


def _resolve_readiness_config(inputs: dict[str, Any]) -> tuple[dict[str, Any], str]:
    raw_cfg = inputs.get("post_apply_ssh_readiness")
    cfg: dict[str, Any]
    if raw_cfg is None:
        cfg = {}
    elif isinstance(raw_cfg, bool):
        cfg = {"enabled": raw_cfg}
    elif isinstance(raw_cfg, dict):
        cfg = dict(raw_cfg)
    else:
        return {}, "inputs.post_apply_ssh_readiness must be a boolean or mapping when set"

    out: dict[str, Any] = {}
    out["enabled"] = as_bool(cfg.get("enabled"), default=True)
    out["required"] = as_bool(cfg.get("required"), default=True)
    out["target_user"] = str(cfg.get("target_user") or inputs.get("ssh_username") or "opsadmin").strip() or "opsadmin"
    out["target_port"] = max(1, as_int(cfg.get("target_port"), default=22))
    out["connectivity_timeout_s"] = max(1, as_int(cfg.get("connectivity_timeout_s"), default=5))
    out["connectivity_wait_s"] = max(0, as_int(cfg.get("connectivity_wait_s"), default=300))
    out["ssh_proxy_jump_auto"] = as_bool(cfg.get("ssh_proxy_jump_auto"), default=True)
    out["ssh_proxy_jump_host"] = str(cfg.get("ssh_proxy_jump_host") or "").strip()
    out["ssh_proxy_jump_user"] = str(cfg.get("ssh_proxy_jump_user") or "").strip()
    out["ssh_proxy_jump_port"] = max(1, as_int(cfg.get("ssh_proxy_jump_port"), default=22))
    out["ssh_private_key_file"] = str(cfg.get("ssh_private_key_file") or "").strip()
    return out, ""


def _resolve_sdn_readiness_config(inputs: dict[str, Any]) -> tuple[dict[str, Any], str]:
    raw_cfg = inputs.get("post_apply_sdn_readiness")
    cfg: dict[str, Any]
    if raw_cfg is None:
        cfg = {}
    elif isinstance(raw_cfg, bool):
        cfg = {"enabled": raw_cfg}
    elif isinstance(raw_cfg, dict):
        cfg = dict(raw_cfg)
    else:
        return {}, "inputs.post_apply_sdn_readiness must be a boolean or mapping when set"

    out: dict[str, Any] = {}
    out["enabled"] = as_bool(cfg.get("enabled"), default=True)
    out["required"] = as_bool(cfg.get("required"), default=True)
    out["timeout_s"] = max(3, as_int(cfg.get("timeout_s"), default=10))
    out["settle_wait_s"] = max(0, as_int(cfg.get("settle_wait_s"), default=5))
    out["proxmox_ssh_port"] = max(1, as_int(cfg.get("proxmox_ssh_port"), default=22))
    out["proxmox_ssh_user"] = str(cfg.get("proxmox_ssh_user") or "").strip()
    out["ssh_private_key_file"] = str(cfg.get("ssh_private_key_file") or "").strip()
    return out, ""


def _iter_network_sdn_expected_gateways(inputs: dict[str, Any], outputs: dict[str, Any]) -> dict[str, list[str]]:
    expected: dict[str, list[str]] = {}

    raw_subnets = outputs.get("subnets")
    if isinstance(raw_subnets, dict):
        for item in raw_subnets.values():
            if not isinstance(item, dict):
                continue
            vnet = str(item.get("vnet") or "").strip()
            cidr = str(item.get("cidr") or "").strip()
            gateway = str(item.get("gateway") or "").strip()
            if not vnet or not cidr or not gateway:
                continue
            try:
                net = ipaddress.ip_network(cidr, strict=True)
                gw = ipaddress.ip_address(gateway)
                if not isinstance(net, ipaddress.IPv4Network) or not isinstance(gw, ipaddress.IPv4Address):
                    continue
            except Exception:
                continue
            token = f"{gw}/{net.prefixlen}"
            expected.setdefault(vnet, [])
            if token not in expected[vnet]:
                expected[vnet].append(token)
        if expected:
            return expected

    raw_vnets = inputs.get("vnets")
    if not isinstance(raw_vnets, dict):
        return expected
    for vnet_name, vnet_item in raw_vnets.items():
        vnet = str(vnet_name or "").strip()
        if not vnet or not isinstance(vnet_item, dict):
            continue
        subnets = vnet_item.get("subnets")
        if not isinstance(subnets, dict):
            continue
        for subnet_item in subnets.values():
            if not isinstance(subnet_item, dict):
                continue
            cidr = str(subnet_item.get("cidr") or "").strip()
            gateway = str(subnet_item.get("gateway") or "").strip()
            if not cidr or not gateway:
                continue
            try:
                net = ipaddress.ip_network(cidr, strict=True)
                gw = ipaddress.ip_address(gateway)
                if not isinstance(net, ipaddress.IPv4Network) or not isinstance(gw, ipaddress.IPv4Address):
                    continue
            except Exception:
                continue
            token = f"{gw}/{net.prefixlen}"
            expected.setdefault(vnet, [])
            if token not in expected[vnet]:
                expected[vnet].append(token)
    return expected


def _iter_network_sdn_expected_vnets(inputs: dict[str, Any], outputs: dict[str, Any]) -> list[str]:
    names: list[str] = []
    raw_vnets = outputs.get("vnets")
    if isinstance(raw_vnets, dict):
        for key in raw_vnets.keys():
            token = str(key or "").strip()
            if token and token not in names:
                names.append(token)
        if names:
            return names
    raw_inputs_vnets = inputs.get("vnets")
    if isinstance(raw_inputs_vnets, dict):
        for key in raw_inputs_vnets.keys():
            token = str(key or "").strip()
            if token and token not in names:
                names.append(token)
    return names


def _ssh_run_proxmox(
    *,
    proxmox_host: str,
    proxmox_user: str,
    proxmox_port: int,
    ssh_private_key_file: str,
    remote_argv: list[str],
    cwd: str,
    env: dict[str, str],
    evidence_dir: Path,
    label: str,
    redact: bool,
    timeout_s: int,
) -> tuple[int, str]:
    ssh_bin = shutil.which("ssh")
    if not ssh_bin:
        return 127, "missing command: ssh"
    argv = [
        ssh_bin,
        "-p",
        str(int(proxmox_port)),
        "-o",
        "BatchMode=yes",
        "-o",
        "StrictHostKeyChecking=no",
        "-o",
        "UserKnownHostsFile=/dev/null",
        "-o",
        f"ConnectTimeout={max(3, int(timeout_s))}",
    ]
    if ssh_private_key_file:
        argv.extend(["-i", ssh_private_key_file])
    argv.append(f"{proxmox_user}@{proxmox_host}")
    argv.extend(remote_argv)
    try:
        r = run_capture(
            argv,
            cwd=cwd,
            env=env,
            evidence_dir=evidence_dir,
            label=label,
            timeout_s=max(5, int(timeout_s) + 5),
            redact=redact,
        )
    except Exception as exc:
        return 1, str(exc)
    return int(r.rc), ""


def run_post_apply_network_sdn_readiness(
    *,
    module_ref: str,
    command_name: str,
    inputs: dict[str, Any],
    outputs: dict[str, Any],
    runtime_root: Path,
    cwd: str,
    env: dict[str, str],
    evidence_dir: Path,
    redact: bool,
) -> tuple[dict[str, Any] | None, list[str], str]:
    if str(module_ref or "").strip() != "core/onprem/network-sdn":
        return None, [], ""
    if str(command_name or "").strip().lower() not in {"apply", "deploy"}:
        return None, [], ""

    warnings: list[str] = []
    cfg, cfg_err = _resolve_sdn_readiness_config(inputs)
    if cfg_err:
        return None, warnings, cfg_err

    summary: dict[str, Any] = {
        "enabled": bool(cfg.get("enabled")),
        "required": bool(cfg.get("required")),
        "status": "skipped",
        "config": {
            "timeout_s": int(cfg.get("timeout_s") or 10),
            "settle_wait_s": int(cfg.get("settle_wait_s") or 5),
            "proxmox_ssh_user": str(cfg.get("proxmox_ssh_user") or ""),
            "proxmox_ssh_port": int(cfg.get("proxmox_ssh_port") or 22),
            "ssh_private_key_file": str(cfg.get("ssh_private_key_file") or ""),
        },
    }
    if not bool(cfg.get("enabled")):
        return summary, warnings, ""

    zone_name = str(outputs.get("zone_name") or inputs.get("zone_name") or "").strip()
    expected_vnets = _iter_network_sdn_expected_vnets(inputs, outputs)
    expected_gateways = _iter_network_sdn_expected_gateways(inputs, outputs)
    summary["expected"] = {
        "zone_name": zone_name,
        "vnets": list(expected_vnets),
        "gateway_ips_by_vnet": expected_gateways,
    }
    if not zone_name:
        summary["status"] = "error"
        summary["error"] = "unable to determine zone_name from outputs or inputs"
        if bool(cfg.get("required")):
            return summary, warnings, str(summary["error"])
        warnings.append(f"post-apply SDN readiness failed (warn-only): {summary['error']}")
        return summary, warnings, ""

    proxmox_host, detected_user = resolve_default_bastion(runtime_root)
    proxmox_user = str(cfg.get("proxmox_ssh_user") or "").strip() or detected_user or "root"
    proxmox_port = int(cfg.get("proxmox_ssh_port") or 22)
    ssh_private_key_file = str(cfg.get("ssh_private_key_file") or "").strip()
    summary["effective_proxmox_ssh"] = {
        "host": proxmox_host,
        "user": proxmox_user,
        "port": proxmox_port,
    }
    if not proxmox_host:
        msg = "proxmox init metadata not found; cannot run live SDN post-apply validation"
        summary["status"] = "error"
        summary["error"] = msg
        if bool(cfg.get("required")):
            return summary, warnings, msg
        warnings.append(f"post-apply SDN readiness failed (warn-only): {msg}")
        return summary, warnings, ""

    settle_wait = int(cfg.get("settle_wait_s") or 0)
    if settle_wait > 0:
        time.sleep(settle_wait)

    timeout_s = int(cfg.get("timeout_s") or 10)

    # Validate zones
    rc, err = _ssh_run_proxmox(
        proxmox_host=proxmox_host,
        proxmox_user=proxmox_user,
        proxmox_port=proxmox_port,
        ssh_private_key_file=ssh_private_key_file,
        remote_argv=["pvesh", "get", "/cluster/sdn/zones", "--output-format", "json"],
        cwd=cwd,
        env=env,
        evidence_dir=evidence_dir,
        label="sdn_zones",
        redact=redact,
        timeout_s=timeout_s,
    )
    if rc != 0:
        msg = f"failed to read Proxmox SDN zones (see sdn_zones.* evidence): {err or f'rc={rc}'}"
        summary["status"] = "error"
        summary["error"] = msg
        if bool(cfg.get("required")):
            return summary, warnings, msg
        warnings.append(f"post-apply SDN readiness failed (warn-only): {msg}")
        return summary, warnings, ""
    try:
        zones_payload = json.loads((evidence_dir / "sdn_zones.stdout.txt").read_text(encoding="utf-8"))
    except Exception as exc:
        msg = f"failed to parse Proxmox SDN zones response: {exc} (see sdn_zones.stdout.txt)"
        summary["status"] = "error"
        summary["error"] = msg
        if bool(cfg.get("required")):
            return summary, warnings, msg
        warnings.append(f"post-apply SDN readiness failed (warn-only): {msg}")
        return summary, warnings, ""
    zone_names: list[str] = []
    if isinstance(zones_payload, list):
        for item in zones_payload:
            if not isinstance(item, dict):
                continue
            token = str(item.get("zone") or item.get("id") or "").strip()
            if token and token not in zone_names:
                zone_names.append(token)
    summary["observed"] = {"zone_names": zone_names}
    if zone_name not in zone_names:
        msg = f"expected Proxmox SDN zone '{zone_name}' not found (observed={zone_names})"
        summary["status"] = "error"
        summary["error"] = msg
        if bool(cfg.get("required")):
            return summary, warnings, msg
        warnings.append(f"post-apply SDN readiness failed (warn-only): {msg}")
        return summary, warnings, ""

    # Validate VNETs and zone binding if available.
    rc, err = _ssh_run_proxmox(
        proxmox_host=proxmox_host,
        proxmox_user=proxmox_user,
        proxmox_port=proxmox_port,
        ssh_private_key_file=ssh_private_key_file,
        remote_argv=["pvesh", "get", "/cluster/sdn/vnets", "--output-format", "json"],
        cwd=cwd,
        env=env,
        evidence_dir=evidence_dir,
        label="sdn_vnets",
        redact=redact,
        timeout_s=timeout_s,
    )
    if rc != 0:
        msg = f"failed to read Proxmox SDN vnets (see sdn_vnets.* evidence): {err or f'rc={rc}'}"
        summary["status"] = "error"
        summary["error"] = msg
        if bool(cfg.get("required")):
            return summary, warnings, msg
        warnings.append(f"post-apply SDN readiness failed (warn-only): {msg}")
        return summary, warnings, ""
    try:
        vnets_payload = json.loads((evidence_dir / "sdn_vnets.stdout.txt").read_text(encoding="utf-8"))
    except Exception as exc:
        msg = f"failed to parse Proxmox SDN vnets response: {exc} (see sdn_vnets.stdout.txt)"
        summary["status"] = "error"
        summary["error"] = msg
        if bool(cfg.get("required")):
            return summary, warnings, msg
        warnings.append(f"post-apply SDN readiness failed (warn-only): {msg}")
        return summary, warnings, ""
    observed_vnets: dict[str, dict[str, Any]] = {}
    if isinstance(vnets_payload, list):
        for item in vnets_payload:
            if not isinstance(item, dict):
                continue
            name = str(item.get("vnet") or item.get("id") or "").strip()
            if not name:
                continue
            observed_vnets[name] = dict(item)
    summary.setdefault("observed", {})
    summary["observed"]["vnet_names"] = sorted(observed_vnets.keys())
    for expected_vnet in expected_vnets:
        item = observed_vnets.get(expected_vnet)
        if item is None:
            msg = f"expected Proxmox SDN vnet '{expected_vnet}' not found (observed={sorted(observed_vnets.keys())})"
            summary["status"] = "error"
            summary["error"] = msg
            if bool(cfg.get("required")):
                return summary, warnings, msg
            warnings.append(f"post-apply SDN readiness failed (warn-only): {msg}")
            return summary, warnings, ""
        observed_zone = str(item.get("zone") or "").strip()
        if observed_zone and observed_zone != zone_name:
            msg = f"vnet '{expected_vnet}' is bound to zone '{observed_zone}', expected '{zone_name}'"
            summary["status"] = "error"
            summary["error"] = msg
            if bool(cfg.get("required")):
                return summary, warnings, msg
            warnings.append(f"post-apply SDN readiness failed (warn-only): {msg}")
            return summary, warnings, ""

    # Validate host-side gateway IP(s) are present on each VNET bridge.
    observed_gateway_addrs: dict[str, list[str]] = {}
    for expected_vnet in expected_vnets:
        label = f"sdn_ip_addr.{expected_vnet}"
        rc, err = _ssh_run_proxmox(
            proxmox_host=proxmox_host,
            proxmox_user=proxmox_user,
            proxmox_port=proxmox_port,
            ssh_private_key_file=ssh_private_key_file,
            remote_argv=["ip", "-4", "-o", "addr", "show", "dev", expected_vnet],
            cwd=cwd,
            env=env,
            evidence_dir=evidence_dir,
            label=label,
            redact=redact,
            timeout_s=timeout_s,
        )
        if rc != 0:
            msg = f"failed to inspect host IPs for vnet '{expected_vnet}' (see {label}.* evidence): {err or f'rc={rc}'}"
            summary["status"] = "error"
            summary["error"] = msg
            if bool(cfg.get("required")):
                return summary, warnings, msg
            warnings.append(f"post-apply SDN readiness failed (warn-only): {msg}")
            return summary, warnings, ""
        ip_out = (evidence_dir / f"{label}.stdout.txt").read_text(encoding="utf-8")
        tokens: list[str] = []
        for line in ip_out.splitlines():
            parts = line.split()
            for idx, part in enumerate(parts):
                if part == "inet" and idx + 1 < len(parts):
                    token = str(parts[idx + 1]).strip()
                    if token:
                        tokens.append(token)
        observed_gateway_addrs[expected_vnet] = tokens
        for expected_gw in expected_gateways.get(expected_vnet, []):
            if expected_gw not in tokens:
                msg = (
                    f"vnet '{expected_vnet}' missing expected host gateway IP '{expected_gw}' "
                    f"(observed={tokens}; see {label}.* evidence)"
                )
                summary["status"] = "error"
                summary["error"] = msg
                if bool(cfg.get("required")):
                    return summary, warnings, msg
                warnings.append(f"post-apply SDN readiness failed (warn-only): {msg}")
                return summary, warnings, ""

    summary.setdefault("observed", {})
    summary["observed"]["host_gateway_ips_by_vnet"] = observed_gateway_addrs
    summary["status"] = "ok"
    return summary, warnings, ""


def run_post_apply_ssh_readiness(
    *,
    module_ref: str,
    command_name: str,
    inputs: dict[str, Any],
    outputs: dict[str, Any],
    runtime_root: Path,
    cwd: str,
    env: dict[str, str],
    evidence_dir: Path,
    redact: bool,
) -> tuple[dict[str, Any] | None, list[str], str]:
    module_ref_value = str(module_ref or "").strip()
    if not (
        module_ref_value.startswith("platform/")
        and module_ref_value.endswith("/platform-vm")
    ):
        return None, [], ""
    if str(command_name or "").strip().lower() != "apply":
        return None, [], ""

    warnings: list[str] = []
    cfg, cfg_err = _resolve_readiness_config(inputs)
    if cfg_err:
        return None, warnings, cfg_err

    summary: dict[str, Any] = {
        "enabled": bool(cfg.get("enabled")),
        "required": bool(cfg.get("required")),
        "status": "skipped",
        "config": {
            "target_user": str(cfg.get("target_user") or ""),
            "target_port": int(cfg.get("target_port") or 22),
            "connectivity_timeout_s": int(cfg.get("connectivity_timeout_s") or 5),
            "connectivity_wait_s": int(cfg.get("connectivity_wait_s") or 300),
            "ssh_proxy_jump_auto": bool(cfg.get("ssh_proxy_jump_auto")),
            "ssh_proxy_jump_host": str(cfg.get("ssh_proxy_jump_host") or ""),
            "ssh_proxy_jump_user": str(cfg.get("ssh_proxy_jump_user") or ""),
            "ssh_proxy_jump_port": int(cfg.get("ssh_proxy_jump_port") or 22),
            "ssh_private_key_file": str(cfg.get("ssh_private_key_file") or ""),
        },
        "targets": [],
    }

    if not bool(cfg.get("enabled")):
        return summary, warnings, ""

    targets, target_warnings = _collect_platform_vm_targets(outputs)
    warnings.extend(target_warnings)
    summary["targets"] = list(targets)
    if not targets:
        summary["status"] = "skipped"
        return summary, warnings, ""

    probe_inputs: dict[str, Any] = {
        "connectivity_check": True,
        "inventory_groups": {"platform_vm_targets": list(targets)},
        "target_user": str(cfg.get("target_user") or "opsadmin"),
        "target_port": int(cfg.get("target_port") or 22),
        "connectivity_timeout_s": int(cfg.get("connectivity_timeout_s") or 5),
        "connectivity_wait_s": int(cfg.get("connectivity_wait_s") or 300),
        "ssh_proxy_jump_auto": bool(cfg.get("ssh_proxy_jump_auto")),
    }
    if str(cfg.get("ssh_private_key_file") or "").strip():
        probe_inputs["ssh_private_key_file"] = str(cfg.get("ssh_private_key_file") or "").strip()
    if str(cfg.get("ssh_proxy_jump_host") or "").strip():
        probe_inputs["ssh_proxy_jump_host"] = str(cfg.get("ssh_proxy_jump_host") or "").strip()
    if str(cfg.get("ssh_proxy_jump_user") or "").strip():
        probe_inputs["ssh_proxy_jump_user"] = str(cfg.get("ssh_proxy_jump_user") or "").strip()
    if int(cfg.get("ssh_proxy_jump_port") or 22) > 0:
        probe_inputs["ssh_proxy_jump_port"] = int(cfg.get("ssh_proxy_jump_port") or 22)

    proxy_auto_note = apply_proxy_jump_auto(probe_inputs, runtime_root)
    if proxy_auto_note:
        warnings.append(proxy_auto_note)
    summary["effective_proxy"] = {
        "host": str(probe_inputs.get("ssh_proxy_jump_host") or ""),
        "user": str(probe_inputs.get("ssh_proxy_jump_user") or ""),
        "port": int(as_int(probe_inputs.get("ssh_proxy_jump_port"), default=22)),
        "auto_note": proxy_auto_note,
    }

    ok, conn_err = connectivity_check(
        command_name="apply",
        inputs=probe_inputs,
        runtime_root=runtime_root,
        cwd=cwd,
        env=env,
        evidence_dir=evidence_dir,
        redact=redact,
    )
    if ok:
        summary["status"] = "ok"
        return summary, warnings, ""

    summary["status"] = "error"
    summary["error"] = conn_err
    if bool(cfg.get("required")):
        return summary, warnings, conn_err

    warnings.append(
        "post-apply SSH readiness failed (warn-only): "
        + str(conn_err)
    )
    return summary, warnings, ""
