#!/usr/bin/env python3
# purpose: Import VM infrastructure dataset into NetBox (VMs, interfaces, and IP addresses)
# adr: ADR-0002_source-of-truth_netbox-driven-inventory
# maintainer: HybridOps.Tech

from __future__ import annotations

import argparse
import csv
import ipaddress
import json
import sys
from pathlib import Path

from .contract import DEFAULT_INTERFACE, DEFAULT_STATUS
from .netbox_api import (
    NetBoxConfigError,
    assign_ip_to_interface,
    delete_vm,
    ensure_cluster,
    ensure_device_role,
    ensure_interface,
    ensure_ip_range,
    ensure_ipam_role,
    ensure_ip,
    ensure_prefix,
    ensure_site,
    ensure_vlan,
    ensure_vm,
    get_cluster,
    get_client,
    list_vms_in_cluster,
    mark_vm_stale,
    normalize_ip,
    probe_client,
    set_vm_primary_ip4,
)
from .paths import vms_auto_csv_path, vms_auto_json_path

MANAGED_TAG = "managed:infra-csv"
STALE_TAG = "stale:infra-csv"


def _normalize_vm_status(value: str) -> str:
    raw = str(value or "").strip().lower()
    if not raw:
        return DEFAULT_STATUS
    if raw in {"true", "1", "up", "running", "started", "online"}:
        return "active"
    if raw in {"false", "0", "down", "stopped", "halted", "offline"}:
        return "offline"
    allowed = {"active", "offline", "planned", "staged", "failed", "decommissioning"}
    if raw in allowed:
        return raw
    return DEFAULT_STATUS


def _parse_int(value: str) -> int | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    try:
        return int(float(raw))
    except Exception:
        return None


def _disk_gb_to_mb(value: str) -> int | None:
    gb = _parse_int(value)
    if gb is None:
        return None
    if gb < 0:
        return None
    return int(gb) * 1024


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog=Path(__file__).name,
        description="Import VMs, VM interfaces, and IP addresses into NetBox from the VM dataset.",
    )
    parser.add_argument("--dry-run", action="store_true", help="Do not modify NetBox; print intended actions.")
    parser.add_argument(
        "--validate-only",
        action="store_true",
        help="Validate dataset contract and exit without calling the NetBox API.",
    )
    parser.add_argument(
        "--dataset",
        dest="dataset_path",
        help="Override input dataset path (.json or .csv). Defaults to vms.auto.json when present.",
    )
    parser.add_argument(
        "--destroy-sync",
        action="store_true",
        help="Retire/delete the listed VMs in NetBox (destroy path) instead of ensuring VM inventory.",
    )
    parser.add_argument(
        "--hard-delete",
        action="store_true",
        help="With --destroy-sync, delete VMs from NetBox instead of soft-retiring them.",
    )
    return parser.parse_args(argv)

def _detect_dataset_kind(rows: list[dict[str, str]]) -> str:
    for r in rows:
        if not isinstance(r, dict):
            continue
        if (r.get("prefix") or "").strip():
            return "ipam_prefixes"
        if (r.get("name") or "").strip():
            return "vms"
    return "unknown"


def _validate_ipam_row(row: dict[str, str], rownum: int) -> list[str]:
    errors: list[str] = []
    site = (row.get("site") or "").strip()
    prefix = (row.get("prefix") or "").strip()
    if not site:
        errors.append(f"row {rownum}: missing required field 'site'")
    if not prefix:
        errors.append(f"row {rownum}: missing required field 'prefix'")
        return errors

    try:
        ipaddress.ip_network(prefix, strict=True)
    except Exception:
        errors.append(f"row {rownum}: prefix is not a valid CIDR: {prefix}")

    vlan_raw = (row.get("vlan_id") or "").strip()
    if vlan_raw:
        try:
            vid = int(vlan_raw)
            if vid <= 0:
                errors.append(f"row {rownum}: vlan_id must be > 0")
        except Exception:
            errors.append(f"row {rownum}: vlan_id is not an integer: {vlan_raw!r}")

    for k in ["gateway", "dhcp_start", "dhcp_end"]:
        v = (row.get(k) or "").strip()
        if not v:
            continue
        try:
            ipaddress.ip_address(v)
        except Exception:
            errors.append(f"row {rownum}: {k} is not a valid IP: {v}")

    return errors


def _compute_static_range(prefix: str, gateway: str, dhcp_start: str) -> tuple[str, str]:
    net = ipaddress.ip_network(prefix, strict=True)
    gw_ip = ipaddress.ip_address(gateway)
    dhcp_start_ip = ipaddress.ip_address(dhcp_start)

    if gw_ip not in net:
        raise ValueError(f"gateway {gateway} not inside prefix {prefix}")
    if dhcp_start_ip not in net:
        raise ValueError(f"dhcp_start {dhcp_start} not inside prefix {prefix}")

    static_start_int = int(gw_ip) + 1
    static_end_int = int(dhcp_start_ip) - 1
    if static_start_int > static_end_int:
        raise ValueError(f"invalid static range for prefix {prefix}: start > end")

    static_start_ip = ipaddress.ip_address(static_start_int)
    static_end_ip = ipaddress.ip_address(static_end_int)
    if static_start_ip not in net or static_end_ip not in net:
        raise ValueError(f"computed static range outside prefix {prefix}")

    return str(static_start_ip), str(static_end_ip)


def _import_ipam_prefixes(client, rows: list[dict[str, str]]) -> int:
    stats = {"prefixes": 0, "ranges": 0, "errors": 0, "skipped": 0}

    for row in rows:
        site_slug = (row.get("site") or "").strip()
        prefix = (row.get("prefix") or "").strip()
        if not site_slug or not prefix:
            stats["skipped"] += 1
            continue

        role_name = (row.get("role") or "").strip() or "hyops-static"
        vnet_name = (row.get("vnet") or "").strip()
        vlan_raw = (row.get("vlan_id") or "").strip()
        gateway = (row.get("gateway") or "").strip()
        dhcp_start = (row.get("dhcp_start") or "").strip()
        dhcp_end = (row.get("dhcp_end") or "").strip()
        status = (row.get("status") or "active").strip().lower() or "active"
        description = (row.get("description") or "").strip()

        vid_value: int | None = None
        if vlan_raw:
            try:
                vid_value = int(vlan_raw)
            except Exception:
                vid_value = None

        try:
            site = ensure_site(client, site_slug)
            role = ensure_ipam_role(client, role_name)

            vlan_obj = None
            if vid_value is not None and vid_value > 0:
                vlan_obj = ensure_vlan(
                    client,
                    vid=vid_value,
                    site_id=int(site["id"]),
                    name=vnet_name or f"{site_slug}-{vid_value}",
                    role_id=int(role["id"]),
                )

            ensured_prefix = ensure_prefix(
                client,
                prefix=prefix,
                site_id=int(site["id"]),
                vlan_id=int(vlan_obj["id"]) if isinstance(vlan_obj, dict) else None,
                role_id=int(role["id"]),
                status=status,
                description=description,
            )
            stats["prefixes"] += 1
            print(f"prefix {prefix} (id={ensured_prefix['id']}) ensured")

            if gateway and dhcp_start:
                static_start, static_end = _compute_static_range(prefix, gateway, dhcp_start)
                static_description = (
                    f"{role_name} static pool ({static_start}-{static_end}"
                    + (
                        f", excludes DHCP {dhcp_start}-{dhcp_end}"
                        if dhcp_end
                        else f", excludes DHCP start {dhcp_start}"
                    )
                    + ")"
                )
                ensured_range = ensure_ip_range(
                    client,
                    start_address=static_start,
                    end_address=static_end,
                    role_id=int(role["id"]),
                    status=status,
                    description=static_description,
                )
                stats["ranges"] += 1
                print(f"  static range {static_start}-{static_end} (id={ensured_range['id']}) ensured")

        except Exception as exc:  # noqa: BLE001
            stats["errors"] += 1
            print(f"prefix {prefix}: ERROR {exc}")

    print("\nSummary:")
    print(f"  Prefixes ensured:      {stats['prefixes']}")
    print(f"  Static ranges ensured: {stats['ranges']}")
    print(f"  Skipped:               {stats['skipped']}")
    print(f"  Errors:                {stats['errors']}")
    return 0 if stats["errors"] == 0 else 4


def _validate_row(row: dict[str, str], rownum: int) -> list[str]:
    errors: list[str] = []

    name = (row.get("name") or "").strip()
    cluster = (row.get("cluster") or "").strip()
    ip_raw = (row.get("ip_address") or "").strip()

    if not name:
        errors.append(f"row {rownum}: missing required field 'name'")
    if not cluster:
        errors.append(f"row {rownum}: missing required field 'cluster'")

    if not ip_raw:
        return errors

    if ip_raw.lower() == "dhcp":
        return errors

    ip_norm = normalize_ip(ip_raw)
    if ip_norm is None:
        errors.append(f"row {rownum}: ip_address is not importable (invalid format)")
    return errors


def _soft_prune_missing_vms(client, rows: list[dict[str, str]]) -> None:
    desired_keys: set[tuple[str, str]] = set()
    clusters: set[str] = set()

    for row in rows:
        name = (row.get("name") or "").strip()
        cluster_name = (row.get("cluster") or "").strip()
        if not name or not cluster_name:
            continue
        desired_keys.add((cluster_name, name))
        clusters.add(cluster_name)

    stats = {
        "evaluated": 0,
        "retired": 0,
        "skipped_unmanaged": 0,
        "errors": 0,
    }

    for cluster_name in sorted(clusters):
        try:
            cluster = ensure_cluster(client, cluster_name)
        except Exception:  # noqa: BLE001
            stats["errors"] += 1
            continue

        try:
            vms = list_vms_in_cluster(client, cluster_id=int(cluster["id"]))
        except Exception:  # noqa: BLE001
            stats["errors"] += 1
            continue

        for vm in vms:
            vm_name = (str(vm.get("name") or "")).strip()
            if not vm_name:
                continue

            key = (cluster_name, vm_name)

            existing_tags_field = vm.get("tags", [])
            tag_names: set[str] = set()
            for t in existing_tags_field:
                if isinstance(t, dict):
                    tag = str(t.get("name") or "").strip()
                else:
                    tag = str(t).strip()
                if tag:
                    tag_names.add(tag)

            tag_lower = {t.lower() for t in tag_names}
            if MANAGED_TAG.lower() not in tag_lower:
                stats["skipped_unmanaged"] += 1
                continue

            stats["evaluated"] += 1

            if key in desired_keys:
                continue

            try:
                mark_vm_stale(client, vm_id=int(vm["id"]), managed_tag=MANAGED_TAG, stale_tag=STALE_TAG)
                stats["retired"] += 1
            except Exception:  # noqa: BLE001
                stats["errors"] += 1

    if stats["retired"]:
        print("\nPrune summary (soft retire):")
        for k in ["evaluated", "retired", "skipped_unmanaged", "errors"]:
            print(f"  {k}: {stats[k]}")


def _destroy_sync_vms(client, rows: list[dict[str, str]], *, hard_delete: bool) -> int:
    targets: set[tuple[str, str]] = set()
    for row in rows:
        name = (row.get("name") or "").strip()
        cluster_name = (row.get("cluster") or "").strip()
        if name and cluster_name:
            targets.add((cluster_name, name))

    stats = {"targeted": 0, "retired": 0, "deleted": 0, "not_found": 0, "errors": 0}
    for cluster_name in sorted({c for c, _ in targets}):
        try:
            cluster = get_cluster(client, cluster_name)
        except Exception as exc:  # noqa: BLE001
            print(f"{cluster_name}: ERROR failed to query cluster ({exc})")
            stats["errors"] += 1
            continue

        cluster_targets = sorted([name for c, name in targets if c == cluster_name])
        if not isinstance(cluster, dict):
            for name in cluster_targets:
                stats["targeted"] += 1
                stats["not_found"] += 1
                print(f"{name}: not found (cluster missing: {cluster_name})")
            continue

        try:
            vms = list_vms_in_cluster(client, cluster_id=int(cluster["id"]))
        except Exception as exc:  # noqa: BLE001
            print(f"{cluster_name}: ERROR failed to list VMs ({exc})")
            stats["errors"] += 1
            continue

        vm_by_name = {str(vm.get("name") or "").strip(): vm for vm in vms if str(vm.get("name") or "").strip()}
        for name in cluster_targets:
            stats["targeted"] += 1
            vm = vm_by_name.get(name)
            if not isinstance(vm, dict):
                stats["not_found"] += 1
                print(f"{name}: not found in NetBox cluster={cluster_name}")
                continue
            try:
                if hard_delete:
                    delete_vm(client, vm_id=int(vm["id"]))
                    stats["deleted"] += 1
                    print(f"{name}: deleted from NetBox cluster={cluster_name}")
                else:
                    mark_vm_stale(client, vm_id=int(vm["id"]), managed_tag=MANAGED_TAG, stale_tag=STALE_TAG)
                    stats["retired"] += 1
                    print(f"{name}: soft-retired in NetBox cluster={cluster_name}")
            except Exception as exc:  # noqa: BLE001
                stats["errors"] += 1
                print(f"{name}: ERROR destroy-sync failed ({exc})")

    print("\nDestroy sync summary:")
    for k in ["targeted", "retired", "deleted", "not_found", "errors"]:
        print(f"  {k}: {stats[k]}")
    return 0 if stats["errors"] == 0 else 4


def _load_rows_from_json(path: Path) -> list[dict[str, str]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        raise ValueError("VM dataset JSON must be a list of objects")

    rows: list[dict[str, str]] = []
    for item in payload:
        if not isinstance(item, dict):
            continue

        normalized: dict[str, str] = {}
        for k, v in item.items():
            key = str(k)
            if v is None:
                normalized[key] = ""
            elif isinstance(v, list) and key == "tags":
                normalized[key] = ";".join(str(t).strip() for t in v if str(t).strip())
            else:
                normalized[key] = v if isinstance(v, str) else str(v)
        rows.append(normalized)

    return rows


def _load_rows_from_csv(path: Path) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    with path.open("r", newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for r in reader:
            rows.append({str(k): (v or "") for k, v in (r or {}).items()})
    return rows


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)

    default_json = vms_auto_json_path()
    default_csv = vms_auto_csv_path()

    if args.dataset_path:
        input_path = Path(args.dataset_path)
    else:
        input_path = default_json if default_json.exists() else default_csv

    print(f"Using dataset: {input_path}")

    if not input_path.exists():
        print(f"Dataset not found: {input_path}")
        return 1

    try:
        if input_path.suffix.lower() == ".json":
            rows = _load_rows_from_json(input_path)
        else:
            rows = _load_rows_from_csv(input_path)
    except Exception as exc:  # noqa: BLE001
        print(f"ERROR: failed to read dataset: {exc}")
        return 2

    print(f"Loaded {len(rows)} rows from dataset")

    kind = _detect_dataset_kind(rows)
    if kind == "unknown":
        print("ERROR: could not detect dataset kind (expected VM inventory or IPAM prefixes dataset)")
        return 2

    validation_errors: list[str] = []
    for i, row in enumerate(rows, start=2):
        normalized = {k: (v or "") for k, v in row.items()}
        if kind == "ipam_prefixes":
            validation_errors.extend(_validate_ipam_row(normalized, i))
        else:
            validation_errors.extend(_validate_row(normalized, i))

    if validation_errors:
        print("Validation failed:")
        for e in validation_errors:
            print(f"  - {e}")
        return 2

    if args.validate_only:
        print(f"Validation OK: {input_path} (rows={len(rows)})")
        return 0

    try:
        client = get_client(dry_run=bool(args.dry_run))
        if not args.dry_run:
            probe_client(client, timeout=5)
    except NetBoxConfigError as exc:
        print(str(exc))
        return 3
    except Exception as exc:  # noqa: BLE001
        print(str(exc))
        return 3

    if kind == "ipam_prefixes":
        return _import_ipam_prefixes(client, rows)

    if args.destroy_sync:
        return _destroy_sync_vms(client, rows, hard_delete=bool(args.hard_delete))

    stats: dict[str, int] = {
        "total_rows": 0,
        "processed": 0,
        "skipped_no_ip": 0,
        "skipped_dhcp": 0,
        "errors": 0,
    }

    for row in rows:
        stats["total_rows"] += 1
        name = (row.get("name") or "").strip()
        ip_raw = (row.get("ip_address") or "").strip()
        cluster_name = (row.get("cluster") or "").strip()

        if not cluster_name or not name:
            stats["errors"] += 1
            print(f"{name or '<missing name>'}: ERROR missing name/cluster; row skipped")
            continue

        if not ip_raw:
            stats["skipped_no_ip"] += 1
            continue

        dhcp = ip_raw.lower() == "dhcp"
        iface_name = (row.get("interface") or "").strip() or DEFAULT_INTERFACE
        vm_status = _normalize_vm_status((row.get("status") or "").strip())

        raw_tags = (row.get("tags") or "").strip()
        vm_tags: list[str] = [t.strip() for t in raw_tags.split(";") if t.strip()]

        ip_assignment = (row.get("ip_assignment") or "").strip().lower()
        if ip_assignment in {"static", "dhcp"}:
            vm_tags.append(f"ip:{ip_assignment}")

        if MANAGED_TAG not in vm_tags:
            vm_tags.append(MANAGED_TAG)

        try:
            cluster = ensure_cluster(client, cluster_name)
            role_id = None
            role_name = (row.get("role") or "").strip()
            if role_name:
                try:
                    role = ensure_device_role(client, role_name)
                    role_id = int(role["id"])
                except Exception as exc:  # noqa: BLE001
                    print(f"{name}: WARN role sync skipped ({exc})")

            vm = ensure_vm(
                client,
                name=name,
                cluster_id=int(cluster["id"]),
                status=vm_status,
                vcpus=_parse_int(row.get("cpu_cores") or ""),
                memory_mb=_parse_int(row.get("memory_mb") or ""),
                disk_mb=_disk_gb_to_mb(row.get("disk_gb") or ""),
                role_id=role_id,
                tags=vm_tags or None,
                external_id=(row.get("external_id") or "").strip() or None,
            )
            iface = ensure_interface(
                client,
                vm_id=int(vm["id"]),
                name=iface_name,
                mac_address=(row.get("mac_address") or "").strip() or None,
            )

            if dhcp:
                stats["processed"] += 1
                stats["skipped_dhcp"] += 1
                print(f"{name}: cluster={cluster_name} iface={iface_name} (DHCP; IP not managed in NetBox)")
                continue

            ip_addr = normalize_ip(ip_raw)
            if ip_addr is None:
                stats["errors"] += 1
                print(f"{name}: ERROR ip_address '{ip_raw}' is invalid")
                continue

            ip = ensure_ip(client, address=ip_addr)
            ip = assign_ip_to_interface(client, ip_id=int(ip["id"]), iface_id=int(iface["id"]))
            set_vm_primary_ip4(client, vm_id=int(vm["id"]), ip_id=int(ip["id"]))
            stats["processed"] += 1
            sizing_bits: list[str] = []
            if _parse_int(row.get("cpu_cores") or "") is not None:
                sizing_bits.append(f"vcpus={_parse_int(row.get('cpu_cores') or '')}")
            if _parse_int(row.get("memory_mb") or "") is not None:
                sizing_bits.append(f"memory_mb={_parse_int(row.get('memory_mb') or '')}")
            if _parse_int(row.get("disk_gb") or "") is not None:
                sizing_bits.append(f"disk_gb={_parse_int(row.get('disk_gb') or '')}")
            sizing_suffix = f" ({', '.join(sizing_bits)})" if sizing_bits else ""
            print(f"{name}: cluster={cluster_name} iface={iface_name} primary_ip4={ip_addr}{sizing_suffix}")

        except Exception as exc:  # noqa: BLE001
            stats["errors"] += 1
            print(f"{name}: ERROR {exc}")

    if not args.dry_run:
        _soft_prune_missing_vms(client, rows)

    print("\nSummary:")
    for key in ["total_rows", "processed", "skipped_no_ip", "skipped_dhcp", "errors"]:
        print(f"  {key}: {stats[key]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
