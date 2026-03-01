#!/usr/bin/env python3
# purpose: Import prefixes and static pools into NetBox from Terraform/Terragrunt outputs.
# adr: ADR-0002_source-of-truth_netbox-driven-inventory
# maintainer: HybridOps.Studio

from __future__ import annotations

import argparse
import csv
import ipaddress
import json
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .netbox_api import (
    NetBoxClient,
    NetBoxConfigError,
    ensure_ipam_role,
    ensure_ip_range,
    ensure_prefix,
    ensure_site,
    ensure_vlan,
    get_client,
    probe_client,
)
from .paths import ipam_prefixes_emit_csv_path, ipam_prefixes_emit_json_path, sdn_terragrunt_dir_path


def _compute_static_range(prefix: str, gateway: str, dhcp_start: str) -> Tuple[str, str]:
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


def _parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        prog="import_prefixes_to_netbox.py",
        description="Import prefixes, VLANs, and static pools into NetBox from Terragrunt outputs.",
    )
    p.add_argument(
        "--terragrunt-dir",
        dest="terragrunt_dir",
        type=Path,
        default=None,
        help="Path to the Terragrunt module directory (defaults to NETBOX_SDN_TERRAGRUNT_DIR or runtime work/stack).",
    )
    p.add_argument(
        "--dataset",
        dest="dataset_path",
        type=Path,
        default=None,
        help="Import from exported IPAM dataset (.json/.csv) instead of calling terragrunt output.",
    )
    p.add_argument(
        "--output-key",
        dest="output_key",
        default="ipam_prefixes",
        help="Terragrunt output key containing the dataset (default: ipam_prefixes).",
    )
    p.add_argument("--dry-run", action="store_true", help="Do not modify NetBox; print intended actions only.")
    p.add_argument("--validate-only", action="store_true", help="Validate the output payload and exit.")

    p.add_argument(
        "--target",
        choices=["onprem-sdn", "cloud"],
        default="onprem-sdn",
        help="Import mode. onprem-sdn requires vlan_id and gateway; cloud imports prefixes without VLAN/static pools.",
    )

    emit = p.add_mutually_exclusive_group()
    emit.add_argument(
        "--emit",
        action="store_true",
        help="Emit a snapshot JSON/CSV under state/netbox/network/ (default).",
    )
    emit.add_argument("--no-emit", action="store_true", help="Do not emit snapshot files.")
    return p.parse_args(argv)


def _run_terragrunt_output_json(module_dir: Path) -> Dict[str, Any]:
    result = subprocess.run(
        ["terragrunt", "output", "-json"],
        cwd=module_dir,
        capture_output=True,
        text=True,
        timeout=90,
        check=False,
    )
    if result.returncode != 0:
        stderr = (result.stderr or "").strip()
        raise RuntimeError(stderr or f"terragrunt output failed (rc={result.returncode})")

    try:
        payload = json.loads(result.stdout or "{}")
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"invalid JSON from terragrunt output: {exc}") from exc

    if not isinstance(payload, dict):
        raise RuntimeError("terragrunt output payload must be an object")
    return payload


def _extract_output_value(outputs: Dict[str, Any], key: str) -> Any:
    raw = outputs.get(key)
    if isinstance(raw, dict) and "value" in raw:
        return raw.get("value")
    return raw


def _normalize_row(item: Dict[str, Any]) -> Dict[str, Any]:
    def _t(k: str) -> str:
        v = item.get(k)
        return "" if v is None else str(v).strip()

    dhcp_enabled = item.get("dhcp_enabled")
    dhcp_enabled_norm: Optional[bool]
    if dhcp_enabled is None:
        dhcp_enabled_norm = None
    else:
        dhcp_enabled_norm = bool(dhcp_enabled)

    return {
        "site": _t("site"),
        "role": _t("role"),
        "vlan_id": item.get("vlan_id"),
        "prefix": _t("prefix"),
        "gateway": _t("gateway"),
        "dhcp_start": _t("dhcp_start"),
        "dhcp_end": _t("dhcp_end"),
        "status": (_t("status") or "active").lower(),
        "description": _t("description"),
        "dhcp_enabled": dhcp_enabled_norm,
    }


def _parse_vlan_id(value: Any) -> Tuple[Optional[int], Optional[str]]:
    if value is None:
        return None, "missing vlan_id"

    s = str(value).strip()
    if not s:
        return None, "missing vlan_id"

    try:
        vid = int(s)
    except (TypeError, ValueError):
        return None, f"vlan_id is not an integer: {value!r}"

    if vid <= 0:
        return None, "vlan_id must be > 0"

    return vid, None


def _validate_rows(rows: List[Dict[str, Any]], *, target: str) -> List[str]:
    errors: List[str] = []

    if target == "onprem-sdn":
        required = ["site", "role", "vlan_id", "prefix", "gateway"]
    else:
        required = ["site", "role", "prefix"]

    for idx, r in enumerate(rows, start=1):
        for k in required:
            if r.get(k) in ("", None):
                errors.append(f"item {idx}: missing required field '{k}'")

        prefix = str(r.get("prefix") or "").strip()
        if prefix:
            try:
                ipaddress.ip_network(prefix, strict=True)
            except Exception:
                errors.append(f"item {idx}: prefix is not a valid CIDR: {prefix}")

        if target == "onprem-sdn":
            _, vlan_err = _parse_vlan_id(r.get("vlan_id"))
            if vlan_err:
                errors.append(f"item {idx}: {vlan_err}")

            gateway = str(r.get("gateway") or "").strip()
            if gateway:
                try:
                    ipaddress.ip_address(gateway)
                except Exception:
                    errors.append(f"item {idx}: gateway is not a valid IP: {gateway}")

            for k in ["dhcp_start", "dhcp_end"]:
                v = str(r.get(k) or "").strip()
                if not v:
                    continue
                try:
                    ipaddress.ip_address(v)
                except Exception:
                    errors.append(f"item {idx}: {k} is not a valid IP: {v}")

    return errors


def _emit_ipam_snapshots(rows: List[Dict[str, Any]], module_dir: Path, output_key: str, *, target: str) -> None:
    csv_path = ipam_prefixes_emit_csv_path()
    json_path = ipam_prefixes_emit_json_path()

    csv_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.parent.mkdir(parents=True, exist_ok=True)

    ordered_fields = [
        "site",
        "role",
        "vlan_id",
        "prefix",
        "gateway",
        "dhcp_start",
        "dhcp_end",
        "status",
        "description",
        "dhcp_enabled",
    ]

    with csv_path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=ordered_fields)
        w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k, "") for k in ordered_fields})

    payload = {
        "generated_at_utc": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
        "source": {"terragrunt_dir": str(module_dir), "output_key": output_key, "target": target},
        "rows": rows,
    }
    json_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    print(f"Emitted: {csv_path}")
    print(f"Emitted: {json_path}")


def _load_rows_from_dataset(dataset_path: Path) -> List[Dict[str, Any]]:
    path = dataset_path.resolve()
    if not path.exists():
        raise FileNotFoundError(f"dataset not found: {path}")

    rows: List[Dict[str, Any]] = []
    if path.suffix.lower() == ".json":
        payload = json.loads(path.read_text(encoding="utf-8"))
        items: Any
        if isinstance(payload, list):
            items = payload
        elif isinstance(payload, dict) and isinstance(payload.get("rows"), list):
            items = payload.get("rows")
        else:
            raise ValueError("IPAM dataset JSON must be a list or an object with a 'rows' list")
        for item in items:
            if isinstance(item, dict):
                rows.append(_normalize_row(item))
        return rows

    with path.open("r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            if isinstance(row, dict):
                rows.append(_normalize_row(row))
    return rows


def _import_prefix_rows(
    *,
    rows: List[Dict[str, Any]],
    client: NetBoxClient,
    target: str,
) -> int:
    errors = _validate_rows(rows, target=target)
    if errors:
        print("Validation failed:")
        for e in errors:
            print(f"  - {e}")
        return 3

    print(f"Using target: {target}")
    print(f"Loaded {len(rows)} IPAM rows")

    stats = {"prefixes": 0, "ranges": 0, "errors": 0, "skipped": 0}

    for r in rows:
        prefix = str(r.get("prefix") or "").strip()
        if not prefix:
            stats["skipped"] += 1
            continue

        site_slug = str(r.get("site") or "").strip()
        role_name = str(r.get("role") or "").strip()
        gateway = str(r.get("gateway") or "").strip()
        dhcp_start = str(r.get("dhcp_start") or "").strip()
        dhcp_end = str(r.get("dhcp_end") or "").strip()
        status = str(r.get("status") or "active").strip().lower() or "active"
        description = str(r.get("description") or "").strip()

        dhcp_enabled_raw = r.get("dhcp_enabled")
        dhcp_enabled = bool(dhcp_enabled_raw) if dhcp_enabled_raw is not None else bool(dhcp_start)

        vid_value: int | None = None
        vlan_id: int | None = None

        if target == "onprem-sdn":
            parsed_vid, vlan_err = _parse_vlan_id(r.get("vlan_id"))
            if vlan_err or parsed_vid is None:
                stats["errors"] += 1
                print(f"prefix {prefix}: ERROR {vlan_err}")
                continue
            vid_value = parsed_vid

        try:
            site = ensure_site(client, site_slug)
            role = ensure_ipam_role(client, role_name)

            if target == "onprem-sdn":
                assert vid_value is not None
                vlan_name = f"{site_slug}-{role_name}-{vid_value}"
                vlan = ensure_vlan(
                    client,
                    vid=vid_value,
                    site_id=int(site["id"]),
                    name=vlan_name,
                    role_id=int(role["id"]),
                )
                vlan_id = int(vlan["id"])

            ensured_prefix = ensure_prefix(
                client,
                prefix=prefix,
                site_id=int(site["id"]),
                vlan_id=vlan_id,
                role_id=int(role["id"]),
                status=status,
                description=description,
            )
            stats["prefixes"] += 1
            print(f"prefix {prefix} (id={ensured_prefix['id']}) ensured")

            if target == "onprem-sdn" and dhcp_enabled and gateway and dhcp_start:
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


def import_prefixes_from_outputs(
    module_dir: Path,
    output_key: str,
    client: NetBoxClient,
    *,
    emit: bool,
    target: str,
) -> int:
    outputs = _run_terragrunt_output_json(module_dir)
    value = _extract_output_value(outputs, output_key)

    if value is None:
        print(f"Terragrunt output key not found: {output_key}")
        return 1

    if not isinstance(value, list):
        print(f"Terragrunt output '{output_key}' must be a list")
        return 2

    rows: List[Dict[str, Any]] = []
    for item in value:
        if isinstance(item, dict):
            rows.append(_normalize_row(item))

    print(f"Using Terragrunt module: {module_dir}")
    print(f"Using output key: {output_key}")
    print(f"Loaded {len(rows)} IPAM rows from Terragrunt outputs")

    if emit:
        _emit_ipam_snapshots(rows, module_dir, output_key, target=target)

    return _import_prefix_rows(rows=rows, client=client, target=target)


def import_prefixes_from_dataset(
    dataset_path: Path,
    client: NetBoxClient,
    *,
    target: str,
) -> int:
    rows = _load_rows_from_dataset(dataset_path)
    print(f"Using dataset: {dataset_path.resolve()}")
    return _import_prefix_rows(rows=rows, client=client, target=target)


def main(argv: Optional[List[str]] = None) -> int:
    args = _parse_args(argv)

    emit = not bool(args.no_emit)
    dataset_path = args.dataset_path.resolve() if args.dataset_path else None

    if dataset_path is None:
        module_dir = (args.terragrunt_dir or sdn_terragrunt_dir_path()).resolve()
        if not module_dir.exists():
            print(f"Terragrunt directory not found: {module_dir}")
            return 1

    if args.validate_only:
        try:
            if dataset_path is not None:
                rows = _load_rows_from_dataset(dataset_path)
                source_desc = str(dataset_path)
            else:
                outputs = _run_terragrunt_output_json(module_dir)
                value = _extract_output_value(outputs, args.output_key)
                if not isinstance(value, list):
                    print(f"Validation failed: output '{args.output_key}' must be a list")
                    return 2
                rows = [_normalize_row(v) for v in value if isinstance(v, dict)]
                source_desc = f"{module_dir} output={args.output_key}"
            errors = _validate_rows(rows, target=args.target)
            if errors:
                print("Validation failed:")
                for e in errors:
                    print(f"  - {e}")
                return 2
            print(f"Validation OK: {source_desc} target={args.target} rows={len(rows)}")
            return 0
        except Exception as exc:  # noqa: BLE001
            print(f"Validation failed: {exc}")
            return 2

    try:
        client = get_client(dry_run=bool(args.dry_run))
        if not args.dry_run:
            probe_client(client, timeout=5)
    except NetBoxConfigError as exc:
        print(str(exc))
        return 2
    except Exception as exc:  # noqa: BLE001
        print(str(exc))
        return 3

    if dataset_path is not None:
        if emit:
            # Dataset mode normally consumes an already-exported snapshot; avoid rewriting by default.
            print("INFO: --dataset mode ignores emit/no-emit; consuming existing exported dataset")
        return import_prefixes_from_dataset(dataset_path, client, target=args.target)

    return import_prefixes_from_outputs(module_dir, args.output_key, client, emit=emit, target=args.target)


if __name__ == "__main__":
    raise SystemExit(main())
