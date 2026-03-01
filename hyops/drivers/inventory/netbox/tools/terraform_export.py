#!/usr/bin/env python3
# purpose: Shared Terraform/Terragrunt export engine for NetBox VM inventory datasets (CSV + JSON).
# adr: ADR-0002_source-of-truth_netbox-driven-inventory
# maintainer: HybridOps.Studio

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Final

from .contract import DEFAULT_INTERFACE, DEFAULT_STATUS, OPTIONAL_FIELDS, REQUIRED_FIELDS
from .csv_io import ensure_header, merge_rows_by_preferred_keys, read_csv, write_csv
from .paths import (
    ipam_prefixes_auto_csv_path,
    ipam_prefixes_auto_json_path,
    vms_auto_csv_path,
    vms_auto_json_path,
)


@dataclass(frozen=True)
class ExportConfig:
    target: str
    terragrunt_root: Path
    logs_root: Path
    artifacts_root: Path
    default_cluster: str
    cluster_prefix: str
    exclude_patterns: tuple[str, ...] = ()
    vm_extractor: Callable[[dict[str, Any]], list[dict[str, Any]]] | None = None
    changed_only: bool = False


SENSITIVE_KEYWORDS: Final[set[str]] = {
    "token",
    "secret",
    "password",
    "passphrase",
    "private",
    "private_key",
    "apikey",
    "api_key",
    "access_key",
    "client_secret",
    "credential",
    "credentials",
}

MAX_SNAPSHOTS: Final[int] = 5


def _safe_print(msg: str) -> None:
    try:
        print(msg)
    except BrokenPipeError:
        try:
            sys.stdout.close()
        except Exception:  # noqa: BLE001
            pass
        raise SystemExit(0)


def _prune_snapshots(directory: Path, suffix: str, max_keep: int = MAX_SNAPSHOTS) -> None:
    try:
        candidates = sorted(
            directory.glob(f"*{suffix}"),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
    except FileNotFoundError:
        return

    if len(candidates) <= max_keep:
        return

    for old_path in candidates[max_keep:]:
        try:
            old_path.unlink()
        except OSError:
            continue


def _as_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def _normalize_netbox_vm_status(value: Any) -> str:
    raw = _as_text(value).strip().lower()
    if not raw:
        return DEFAULT_STATUS
    if raw in {"true", "1", "up", "running", "started", "online"}:
        return "active"
    if raw in {"false", "0", "down", "stopped", "halted", "offline"}:
        return "offline"
    if raw in {"active", "offline", "planned", "staged", "failed", "decommissioning"}:
        return raw
    return DEFAULT_STATUS

def _out_value(outputs: dict[str, Any], key: str) -> str:
    body = outputs.get(key)
    if isinstance(body, dict):
        v = body.get("value")
        return str(v).strip() if v is not None else ""
    return ""

def _out_any(outputs: dict[str, Any], key: str) -> Any:
    raw = outputs.get(key)
    if isinstance(raw, dict):
        return raw.get("value")
    return None

def _json_fingerprint(payload: Any) -> str:
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _read_json(path: Path) -> Any | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return None


def find_vm_modules(root_path: Path, exclude_patterns: tuple[str, ...]) -> list[Path]:
    modules: list[Path] = []

    for terragrunt_file in root_path.rglob("terragrunt.hcl"):
        module_dir = terragrunt_file.parent
        if ".terragrunt-cache" in module_dir.parts:
            continue

        relative_path = module_dir.relative_to(root_path)
        rel_s = str(relative_path)
        if any(pattern in rel_s for pattern in exclude_patterns):
            continue

        modules.append(relative_path)

    return sorted(modules)


def _parse_env_and_rel(module_path: Path) -> tuple[str, Path]:
    parts = list(module_path.parts)
    if not parts:
        return "unknown", Path("unknown")

    if parts[0] == "core":
        rel = Path(*parts[1:]) if len(parts) > 1 else Path("root")
        return "core", rel

    if parts[0] == "environments" and len(parts) > 1:
        env = parts[1]
        rel = Path(*parts[2:]) if len(parts) > 2 else Path("root")
        return env, rel

    return "unknown", module_path


def _is_no_state_yet(stderr: str) -> bool:
    s = (stderr or "").lower()
    return (
        ("could not read state version outputs" in s and "resource not found" in s)
        or ("no stored state was found" in s)
        or ("state snapshot was not found" in s)
    )


def _run_terragrunt_output(module_path: Path, terragrunt_root: Path) -> dict[str, Any] | None:
    full_path = terragrunt_root / module_path

    result = subprocess.run(
        ["terragrunt", "output", "-json"],
        cwd=full_path,
        capture_output=True,
        text=True,
        timeout=90,
        check=False,
    )

    if result.returncode != 0:
        stderr = (result.stderr or "").strip()
        if _is_no_state_yet(stderr):
            return None
        return None

    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError:
        return None


def _is_sensitive_key(key: str) -> bool:
    k = key.strip().lower()
    if "public" in k:
        return False
    return any(word in k for word in SENSITIVE_KEYWORDS)


def _scrub(value: Any) -> Any:
    if isinstance(value, dict):
        out: dict[str, Any] = {}
        for k, v in value.items():
            ks = str(k)
            out[ks] = "<redacted>" if _is_sensitive_key(ks) else _scrub(v)
        return out

    if isinstance(value, list):
        return [_scrub(v) for v in value]

    if isinstance(value, str) and "-----BEGIN" in value:
        return "<redacted>"

    return value


def redact_outputs(outputs: dict[str, Any]) -> dict[str, Any]:
    redacted: dict[str, Any] = {}

    for key, body in outputs.items():
        if not isinstance(body, dict):
            redacted[key] = body
            continue

        out_body = dict(body)
        if _is_sensitive_key(key):
            out_body["value"] = "<redacted>"
        else:
            out_body["value"] = _scrub(body.get("value"))
        redacted[key] = out_body

    return redacted


def _write_outputs_json(module_path: Path, outputs: dict[str, Any], config: ExportConfig, run_ts: str) -> bool:
    env, rel = _parse_env_and_rel(module_path)

    logs_dir = config.logs_root / env / rel
    logs_dir.mkdir(parents=True, exist_ok=True)
    logs_path = logs_dir / "outputs.json"
    logs_snap = logs_dir / f"{run_ts}-outputs.json"

    artifacts_dir = config.artifacts_root / env / rel
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    artifacts_path = artifacts_dir / "outputs.redacted.json"
    artifacts_snap = artifacts_dir / f"{run_ts}-outputs.redacted.json"

    redacted = redact_outputs(outputs)

    if config.changed_only and artifacts_path.exists():
        prev = _read_json(artifacts_path)
        if prev is not None and _json_fingerprint(prev) == _json_fingerprint(redacted):
            return False

    payload = json.dumps(outputs, indent=2, sort_keys=True) + "\n"
    logs_path.write_text(payload, encoding="utf-8")
    logs_snap.write_text(payload, encoding="utf-8")
    _prune_snapshots(logs_dir, "-outputs.json")

    redacted_payload = json.dumps(redacted, indent=2, sort_keys=True) + "\n"
    artifacts_path.write_text(redacted_payload, encoding="utf-8")
    artifacts_snap.write_text(redacted_payload, encoding="utf-8")
    _prune_snapshots(artifacts_dir, "-outputs.redacted.json")

    return True


def _extract_ip_and_assignment(outputs: dict[str, Any]) -> tuple[str, str]:
    raw = outputs.get("ip_address")
    if isinstance(raw, dict):
        val = raw.get("value")
        if isinstance(val, str) and val.strip():
            return val.strip(), "static"

    cfg = outputs.get("ip_address_configured")
    if isinstance(cfg, dict):
        val = cfg.get("value")
        if isinstance(val, str) and val.strip():
            return val.strip(), "static"

    ipv4 = outputs.get("ipv4_addresses")
    if isinstance(ipv4, dict):
        value = ipv4.get("value")
        if isinstance(value, list):
            flat: list[str] = []
            for group in value:
                if isinstance(group, list):
                    for ip in group:
                        if isinstance(ip, str) and ip.strip():
                            flat.append(ip.strip())
                elif isinstance(group, str) and group.strip():
                    flat.append(group.strip())
            for ip in flat:
                if not ip.startswith("127."):
                    return ip, "dhcp"

    return "", ""


def _extract_ip_and_assignment_from_vm(vm_data: dict[str, Any]) -> tuple[str, str]:
    cfg = vm_data.get("ip_address_configured")
    if isinstance(cfg, str) and cfg.strip():
        return cfg.strip(), "static"

    ip_val = vm_data.get("ip_address")
    if isinstance(ip_val, str) and ip_val.strip():
        return ip_val.strip(), "static"

    ipv4 = vm_data.get("ipv4_addresses")
    if isinstance(ipv4, list):
        flat: list[str] = []
        for group in ipv4:
            if isinstance(group, list):
                for ip in group:
                    if isinstance(ip, str) and ip.strip():
                        flat.append(ip.strip())
            elif isinstance(group, str) and group.strip():
                flat.append(group.strip())
        for ip in flat:
            if not ip.startswith("127."):
                return ip, "dhcp"

    return "", ""


def extract_vm_data_default(outputs: dict[str, Any]) -> list[dict[str, Any]]:
    vms: list[dict[str, Any]] = []

    if "vm_name" in outputs:
        ip_value, ip_assignment = _extract_ip_and_assignment(outputs)
        tags_val = outputs.get("tags", {}).get("value", [])
        tags_str = ";".join(str(t).strip() for t in tags_val if str(t).strip())
        private_ip = _out_value(outputs, "ip_private") or _out_value(outputs, "ip_address_configured")
        if private_ip and private_ip == ip_value:
            private_ip = ""

        vms.append(
            {
                "name": outputs["vm_name"]["value"],
                "vm_id": _as_text(outputs.get("vm_id", {}).get("value", "")),
                "cpu_cores": _as_text(outputs.get("cpu_cores", {}).get("value", 2)),
                "memory_mb": _as_text(outputs.get("memory_mb", {}).get("value", 2048)),
                "disk_gb": _as_text(outputs.get("disk_gb", {}).get("value", 20)),
                "ip_address": ip_value,
                "ip_assignment": ip_assignment,
                "mac_address": outputs.get("mac_address", {}).get("value", ""),
                "role": _as_text(outputs.get("role", {}).get("value", "")),
                "tags": tags_str,
                "status": _normalize_netbox_vm_status(outputs.get("status", {}).get("value", "")),
                "ip_private": private_ip,
            }
        )

    if "vms" in outputs:
        raw_vms = outputs["vms"].get("value", {})
        if isinstance(raw_vms, dict):
            for vm_data in raw_vms.values():
                if not isinstance(vm_data, dict):
                    continue

                name = str(vm_data.get("vm_name", "")).strip()
                if not name:
                    continue

                ip_value, ip_assignment = _extract_ip_and_assignment_from_vm(vm_data)
                private_ip = str(vm_data.get("ip_private", "")).strip() or str(vm_data.get("ip_address_configured", "")).strip()
                if private_ip and private_ip == ip_value:
                    private_ip = ""

                tags_val = vm_data.get("tags", [])
                if isinstance(tags_val, str):
                    tags_str = tags_val
                else:
                    tags_str = ";".join(str(t).strip() for t in tags_val if str(t).strip())

                vms.append(
                    {
                        "name": name,
                        "vm_id": _as_text(vm_data.get("vm_id", "")),
                        "cpu_cores": _as_text(vm_data.get("cpu_cores", 2)),
                        "memory_mb": _as_text(vm_data.get("memory_mb", 2048)),
                        "disk_gb": _as_text(vm_data.get("disk_gb", 20)),
                        "ip_address": ip_value,
                        "ip_assignment": ip_assignment,
                        "mac_address": vm_data.get("mac_address", ""),
                        "role": _as_text(vm_data.get("role", "")),
                        "tags": tags_str,
                        "status": _normalize_netbox_vm_status(vm_data.get("status", "")),
                        "ip_private": private_ip,
                    }
                )

    return vms


def extract_ipam_prefixes_default(outputs: dict[str, Any]) -> list[dict[str, Any]]:
    """Extract IPAM prefix rows from Terragrunt outputs (best-effort).

    Expected output shape (from core/onprem/network-sdn):
    - zone_name: string
    - vnets: map(string => { vlan_id = number, ... })
    - subnets: map(string => { cidr, gateway, dhcp_range_start, dhcp_range_end, dhcp_enabled, vnet, ... })
    """
    zone_name = str(_out_any(outputs, "zone_name") or "").strip()
    vnets = _out_any(outputs, "vnets")
    subnets = _out_any(outputs, "subnets")

    if not isinstance(subnets, dict):
        return []

    rows: list[dict[str, Any]] = []
    for subnet_key, subnet in subnets.items():
        if not isinstance(subnet, dict):
            continue

        prefix = str(subnet.get("cidr") or "").strip()
        if not prefix:
            continue

        vnet_name = str(subnet.get("vnet") or "").strip()

        vlan_id: Any = None
        if isinstance(vnets, dict) and vnet_name:
            vnet = vnets.get(vnet_name)
            if isinstance(vnet, dict) and vnet.get("vlan_id") is not None:
                vlan_id = vnet.get("vlan_id")

        rows.append(
            {
                "site": zone_name or "onprem",
                "role": "hyops-static",
                "vnet": vnet_name,
                "vlan_id": vlan_id,
                "prefix": prefix,
                "gateway": str(subnet.get("gateway") or "").strip(),
                "dhcp_start": str(subnet.get("dhcp_range_start") or "").strip(),
                "dhcp_end": str(subnet.get("dhcp_range_end") or "").strip(),
                "dhcp_enabled": subnet.get("dhcp_enabled"),
                "status": "active",
                "description": str(subnet.get("description") or "").strip()
                or f"hyops {zone_name or 'onprem'} {vnet_name or subnet_key}",
            }
        )

    return rows


def _infer_cluster(row: dict[str, Any], config: ExportConfig) -> str:
    existing = _as_text(row.get("cluster")).strip()
    if existing:
        return existing

    tags = {t.strip().lower() for t in _as_text(row.get("tags")).split(";") if t.strip()}

    for env in ["dev", "staging", "prod", "production"]:
        if env in tags:
            env_key = "prod" if env == "production" else env
            return f"{config.cluster_prefix}-{env_key}"

    return config.default_cluster


def _extend_header(header: list[str], rows: list[dict[str, Any]]) -> list[str]:
    seen = set(header)
    for r in rows:
        for k in r.keys():
            if k and k not in seen:
                seen.add(k)
                header.append(k)
    return header


def _process_module(
    module_path: Path,
    run_ts: str,
    config: ExportConfig,
) -> tuple[Path, list[dict[str, Any]], list[dict[str, Any]], str | None]:
    try:
        outputs = _run_terragrunt_output(module_path, terragrunt_root=config.terragrunt_root)
        if not outputs:
            return module_path, [], [], "no outputs or not deployed"

        changed = _write_outputs_json(module_path, outputs, config, run_ts)
        if config.changed_only and not changed:
            return module_path, [], [], "unchanged"

        extractor = config.vm_extractor or extract_vm_data_default
        vms = extractor(outputs)
        ipam_rows = extract_ipam_prefixes_default(outputs)

        if not vms and not ipam_rows:
            return module_path, [], [], "no exportable outputs"

        rel_path = module_path.as_posix()
        for vm in vms:
            if not isinstance(vm, dict):
                continue
            if not str(vm.get("tf_address") or "").strip():
                vm["tf_address"] = rel_path

        for r in ipam_rows:
            if not isinstance(r, dict):
                continue
            if not str(r.get("tf_address") or "").strip():
                r["tf_address"] = rel_path

        return module_path, vms, ipam_rows, None
    except subprocess.TimeoutExpired:
        return module_path, [], [], "terragrunt output timed out"
    except Exception as exc:  # noqa: BLE001
        return module_path, [], [], f"error: {exc}"


def run_export(args: Any, config: ExportConfig) -> int:
    run_ts = datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
    terragrunt_root = Path(getattr(args, "terragrunt_root", config.terragrunt_root) or config.terragrunt_root).resolve()

    only_modules = [Path(p) for p in getattr(args, "only_module", []) if str(p).strip()]
    if only_modules:
        modules = sorted(only_modules)
        _safe_print(f"export_infra: target={config.target} terragrunt_root={terragrunt_root} only={len(modules)}")
    else:
        _safe_print(f"export_infra: target={config.target} terragrunt_root={terragrunt_root}")
        modules = find_vm_modules(terragrunt_root, config.exclude_patterns)
        _safe_print(f"export_infra: discovered {len(modules)} modules")

    all_vms: list[dict[str, Any]] = []
    all_ipam: list[dict[str, Any]] = []

    with ThreadPoolExecutor(max_workers=5) as executor:
        futures = {executor.submit(_process_module, m, run_ts, config): m for m in modules}

        for future in as_completed(futures):
            module_path, vms, ipam_rows, error = future.result()
            if vms:
                all_vms.extend(vms)
                vm_names = ", ".join(sorted(str(vm.get("name", "")) for vm in vms if vm.get("name")))
                _safe_print(f"  ok   {module_path} -> {vm_names}")
            elif ipam_rows:
                all_ipam.extend(ipam_rows)
                _safe_print(f"  ok   {module_path} -> ipam_prefixes={len(ipam_rows)}")
            else:
                _safe_print(f"  skip {module_path} -> {error}")

    if not all_vms and not all_ipam:
        _safe_print("export_infra: no exportable assets discovered from terragrunt output")
        return 0

    if all_vms:
        unique_vms = {str(vm["name"]): vm for vm in all_vms if str(vm.get("name", "")).strip()}
        unique_vms_list = list(unique_vms.values())

        csv_path = vms_auto_csv_path()
        json_path = vms_auto_json_path()

        csv_path.parent.mkdir(parents=True, exist_ok=True)
        json_path.parent.mkdir(parents=True, exist_ok=True)

        existing_header: list[str] = []
        existing_rows: list[dict[str, Any]] = []
        if csv_path.exists():
            existing_header, existing_rows = read_csv(csv_path)

        existing_rows = [r for r in existing_rows if (r.get("name") or "").strip()]
        kept_rows = [r for r in existing_rows if _as_text(r.get("source")).strip() != config.target]

        for r in unique_vms_list:
            r["interface"] = _as_text(r.get("interface")).strip() or DEFAULT_INTERFACE
            r["status"] = _as_text(r.get("status")).strip() or DEFAULT_STATUS
            r["source"] = _as_text(r.get("source")).strip() or config.target
            r["cluster"] = _infer_cluster(r, config)

            if not _as_text(r.get("external_id")).strip():
                vm_id = _as_text(r.get("vm_id")).strip()
                if vm_id:
                    r["external_id"] = f"{r['source']}:{vm_id}"

        merged_rows = merge_rows_by_preferred_keys(
            existing=kept_rows,
            new=unique_vms_list,
            keys=["external_id", "tf_address", "name"],
        )
        merged_rows = [r for r in merged_rows if (r.get("name") or "").strip()]

        for r in merged_rows:
            r["interface"] = _as_text(r.get("interface")).strip() or DEFAULT_INTERFACE
            r["status"] = _as_text(r.get("status")).strip() or DEFAULT_STATUS
            r["cluster"] = _infer_cluster(r, config)

            src = _as_text(r.get("source")).strip()
            vm_id = _as_text(r.get("vm_id")).strip()
            if not src and vm_id:
                src = config.target
            r["source"] = src

            if not _as_text(r.get("external_id")).strip() and vm_id and src:
                r["external_id"] = f"{src}:{vm_id}"

        errors: list[str] = []
        for i, r in enumerate(merged_rows, start=2):
            ip_text = _as_text(r.get("ip_address")).strip()
            if not ip_text:
                continue
            for f_name in REQUIRED_FIELDS:
                value_text = _as_text(r.get(f_name)).strip()
                if not value_text:
                    errors.append(f"row {i}: missing required field '{f_name}'")

        if errors:
            _safe_print("Validation failed:")
            for e in errors:
                _safe_print(f"  - {e}")
            return 2

        header = ensure_header(existing_header, REQUIRED_FIELDS, OPTIONAL_FIELDS)
        header = _extend_header(header, merged_rows)

        if getattr(args, "validate_only", False):
            _safe_print(f"Validation OK: {csv_path} (rows={len(merged_rows)})")
            return 0

        if getattr(args, "dry_run", False):
            _safe_print(
                f"dry-run: would write {csv_path} (rows={len(merged_rows)} header={len(header)}) and {json_path}"
            )
            return 0

        rows_sorted = sorted(merged_rows, key=lambda r: (r.get("name") or ""))
        write_csv(csv_path, header, rows_sorted)
        json_path.write_text(json.dumps(rows_sorted, indent=2, sort_keys=True) + "\n", encoding="utf-8")

        _safe_print(f"export: {config.target} -> {csv_path} (rows={len(rows_sorted)})")
        _safe_print(f"export: vms json -> {json_path} (rows={len(rows_sorted)})")

    if all_ipam:
        ipam_csv_path = ipam_prefixes_auto_csv_path()
        ipam_json_path = ipam_prefixes_auto_json_path()
        ipam_csv_path.parent.mkdir(parents=True, exist_ok=True)
        ipam_json_path.parent.mkdir(parents=True, exist_ok=True)

        existing_ipam_header: list[str] = []
        existing_ipam_rows: list[dict[str, Any]] = []
        if ipam_csv_path.exists():
            existing_ipam_header, existing_ipam_rows = read_csv(ipam_csv_path)

        existing_ipam_rows = [r for r in existing_ipam_rows if (r.get("prefix") or "").strip()]
        kept_ipam_rows = [
            r for r in existing_ipam_rows if _as_text(r.get("source")).strip() != config.target
        ]

        for r in all_ipam:
            if not isinstance(r, dict):
                continue
            r["source"] = _as_text(r.get("source")).strip() or config.target
            r["site"] = _as_text(r.get("site")).strip() or "onprem"
            r["role"] = _as_text(r.get("role")).strip() or "hyops-static"
            r["status"] = _as_text(r.get("status")).strip().lower() or "active"
            prefix = _as_text(r.get("prefix")).strip()
            vnet = _as_text(r.get("vnet")).strip()
            r["external_id"] = _as_text(r.get("external_id")).strip() or f"{r['source']}:{r['site']}:{prefix}:{vnet}"

        merged_ipam = merge_rows_by_preferred_keys(
            existing=kept_ipam_rows,
            new=all_ipam,
            keys=["external_id", "tf_address", "prefix"],
        )
        merged_ipam = [r for r in merged_ipam if (r.get("prefix") or "").strip()]

        ipam_header_required = [
            "external_id",
            "source",
            "site",
            "role",
            "vnet",
            "vlan_id",
            "prefix",
            "gateway",
            "dhcp_start",
            "dhcp_end",
            "dhcp_enabled",
            "status",
            "description",
            "tf_address",
        ]
        ipam_header = ensure_header(existing_ipam_header, ipam_header_required, [])
        ipam_header = _extend_header(ipam_header, merged_ipam)

        # If validate-only is set and we only emitted IPAM, return success.
        if getattr(args, "validate_only", False) and not all_vms:
            _safe_print(f"Validation OK: {ipam_csv_path} (rows={len(merged_ipam)})")
            return 0

        if getattr(args, "dry_run", False):
            _safe_print(
                f"dry-run: would write {ipam_csv_path} (rows={len(merged_ipam)} header={len(ipam_header)}) and {ipam_json_path}"
            )
            return 0

        ipam_sorted = sorted(merged_ipam, key=lambda r: (r.get("site") or "", r.get("prefix") or ""))
        write_csv(ipam_csv_path, ipam_header, ipam_sorted)
        ipam_json_path.write_text(json.dumps(ipam_sorted, indent=2, sort_keys=True) + "\n", encoding="utf-8")

        _safe_print(f"export: ipam prefixes -> {ipam_csv_path} (rows={len(ipam_sorted)})")
        _safe_print(f"export: ipam prefixes json -> {ipam_json_path} (rows={len(ipam_sorted)})")

    _safe_print(f"export_infra: terraform outputs logs -> {config.logs_root}")
    _safe_print(f"export_infra: terraform outputs artifacts -> {config.artifacts_root}")

    return 0
