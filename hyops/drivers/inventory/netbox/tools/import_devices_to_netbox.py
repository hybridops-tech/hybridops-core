#!/usr/bin/env python3
# purpose: Import DCIM devices, interfaces, and management IPs into NetBox from devices.manual.csv.
# adr: ADR-0002_source-of-truth_netbox-driven-inventory
# maintainer: HybridOps.Tech

from __future__ import annotations

import argparse
import csv
import re
from pathlib import Path
from typing import Any

from .netbox_api import NetBoxClient, NetBoxConfigError, get_client, normalize_ip, ensure_site
from .paths import devices_manual_csv_path


def _slugify(value: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", value.strip().lower())
    s = re.sub(r"-{2,}", "-", s).strip("-")
    return s or "unnamed"


def _split_tags(raw: str) -> list[str]:
    return [t.strip() for t in (raw or "").split(";") if t.strip()]


def _get_one(client: NetBoxClient, path: str, params: dict[str, Any]) -> dict[str, Any] | None:
    r = client.session.get(f"{client.base_url}{path}", params=params, timeout=30)
    r.raise_for_status()
    payload = r.json()
    if not isinstance(payload, dict):
        return None
    results = payload.get("results")
    if isinstance(results, list) and results:
        first = results[0]
        return first if isinstance(first, dict) else None
    return None


def _post(client: NetBoxClient, path: str, payload: dict[str, Any]) -> dict[str, Any]:
    if client.dry_run:
        print(f"dry-run: POST {path} {payload}")
        return {"id": -1, **payload}

    r = client.session.post(f"{client.base_url}{path}", json=payload, timeout=30)
    r.raise_for_status()
    return r.json()


def _patch(client: NetBoxClient, path: str, payload: dict[str, Any]) -> dict[str, Any]:
    if client.dry_run:
        print(f"dry-run: PATCH {path} {payload}")
        return payload

    r = client.session.patch(f"{client.base_url}{path}", json=payload, timeout=30)
    r.raise_for_status()
    return r.json()


def ensure_device_role(client: NetBoxClient, role: str) -> dict[str, Any]:
    slug = _slugify(role)
    found = _get_one(client, "/api/dcim/device-roles/", {"slug": slug})
    if found:
        return found
    return _post(client, "/api/dcim/device-roles/", {"name": role, "slug": slug})


def ensure_manufacturer(client: NetBoxClient, name: str) -> dict[str, Any]:
    slug = _slugify(name)
    found = _get_one(client, "/api/dcim/manufacturers/", {"slug": slug})
    if found:
        return found
    return _post(client, "/api/dcim/manufacturers/", {"name": name, "slug": slug})


def ensure_device_type(client: NetBoxClient, manufacturer_id: int, model: str) -> dict[str, Any]:
    slug = _slugify(model)
    found = _get_one(client, "/api/dcim/device-types/", {"slug": slug, "manufacturer_id": manufacturer_id})
    if not found:
        found = _get_one(client, "/api/dcim/device-types/", {"slug": slug})
    if found:
        return found
    return _post(
        client,
        "/api/dcim/device-types/",
        {"manufacturer": manufacturer_id, "model": model, "slug": slug},
    )


def ensure_platform(client: NetBoxClient, name: str) -> dict[str, Any]:
    slug = _slugify(name)
    found = _get_one(client, "/api/dcim/platforms/", {"slug": slug})
    if found:
        return found
    return _post(client, "/api/dcim/platforms/", {"name": name, "slug": slug})


def ensure_device(
    client: NetBoxClient,
    *,
    name: str,
    device_type_id: int,
    role_id: int,
    site_id: int,
    platform_id: int | None,
    status: str,
    serial: str,
    asset_tag: str,
    description: str,
    tags: list[str],
) -> dict[str, Any]:
    found = _get_one(client, "/api/dcim/devices/", {"name": name, "site_id": site_id})

    payload: dict[str, Any] = {
        "name": name,
        "device_type": device_type_id,
        "role": role_id,
        "site": site_id,
        "status": status,
        "description": description,
    }
    if platform_id is not None:
        payload["platform"] = platform_id
    if serial:
        payload["serial"] = serial
    if asset_tag:
        payload["asset_tag"] = asset_tag
    if tags:
        payload["tags"] = tags

    if not found:
        return _post(client, "/api/dcim/devices/", payload)

    _patch(client, f"/api/dcim/devices/{int(found['id'])}/", payload)
    found.update(payload)
    return found


def ensure_interface(client: NetBoxClient, *, device_id: int, name: str, iface_type: str = "virtual") -> dict[str, Any]:
    found = _get_one(client, "/api/dcim/interfaces/", {"device_id": device_id, "name": name})
    if found:
        return found
    return _post(client, "/api/dcim/interfaces/", {"device": device_id, "name": name, "type": iface_type})


def ensure_ip(client: NetBoxClient, address: str) -> dict[str, Any]:
    found = _get_one(client, "/api/ipam/ip-addresses/", {"address": address})
    if found:
        return found
    return _post(client, "/api/ipam/ip-addresses/", {"address": address, "status": "active"})


def assign_ip_to_interface(client: NetBoxClient, *, ip_id: int, interface_id: int) -> None:
    _patch(
        client,
        f"/api/ipam/ip-addresses/{ip_id}/",
        {"assigned_object_type": "dcim.interface", "assigned_object_id": interface_id},
    )


def set_device_primary_ip4(client: NetBoxClient, *, device_id: int, ip_id: int) -> None:
    _patch(client, f"/api/dcim/devices/{device_id}/", {"primary_ip4": ip_id})


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(prog="import_devices_to_netbox.py")
    p.add_argument("--csv", dest="csv_path", type=Path, default=None, help="Override devices dataset path.")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--validate-only", action="store_true")
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    csv_path = args.csv_path or devices_manual_csv_path()

    if not csv_path.exists():
        print(f"devices dataset not found: {csv_path}")
        return 1

    try:
        client = get_client(dry_run=bool(args.dry_run))
    except NetBoxConfigError as exc:
        print(str(exc))
        return 2

    required = {"name", "site", "role", "manufacturer", "device_type"}
    rows: list[dict[str, str]] = []
    with csv_path.open("r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        missing = required - set(reader.fieldnames or [])
        if missing:
            print(f"devices CSV missing required columns: {', '.join(sorted(missing))}")
            return 3

        for r in reader:
            row = {k: (v or "").strip() for k, v in r.items() if k}
            if not row.get("name"):
                continue
            rows.append(row)

    errors: list[str] = []
    for i, r in enumerate(rows, start=2):
        for col in sorted(required):
            if not r.get(col):
                errors.append(f"row {i}: missing {col}")

    if errors:
        print("Validation failed:")
        for e in errors:
            print(f"  - {e}")
        return 4

    if args.validate_only:
        print(f"Validation OK: {csv_path} (rows={len(rows)})")
        return 0

    stats = {"processed": 0, "errors": 0, "ip_assigned": 0}

    for r in rows:
        name = r.get("name", "")
        site_slug = r.get("site", "")
        role_name = r.get("role", "")
        manufacturer_name = r.get("manufacturer", "")
        model = r.get("device_type", "")

        platform_name = r.get("platform", "")
        status = (r.get("status") or "active").strip().lower() or "active"
        serial = r.get("serial", "")
        asset_tag = r.get("asset_tag", "")
        description = r.get("description", "")
        tags = _split_tags(r.get("tags", ""))

        mgmt_iface = r.get("mgmt_interface") or "mgmt0"
        mgmt_iface_type = r.get("mgmt_interface_type") or "virtual"
        mgmt_ip_raw = r.get("mgmt_ip", "")

        try:
            site = ensure_site(client, site_slug)
            role = ensure_device_role(client, role_name)
            mfg = ensure_manufacturer(client, manufacturer_name)
            dtype = ensure_device_type(client, manufacturer_id=int(mfg["id"]), model=model)
            platform = ensure_platform(client, platform_name) if platform_name else None

            dev = ensure_device(
                client,
                name=name,
                device_type_id=int(dtype["id"]),
                role_id=int(role["id"]),
                site_id=int(site["id"]),
                platform_id=(int(platform["id"]) if platform else None),
                status=status,
                serial=serial,
                asset_tag=asset_tag,
                description=description,
                tags=tags,
            )

            if mgmt_ip_raw:
                mgmt_ip = normalize_ip(mgmt_ip_raw) or ""
                if not mgmt_ip:
                    raise ValueError(f"invalid mgmt_ip '{mgmt_ip_raw}'")
                iface = ensure_interface(
                    client,
                    device_id=int(dev["id"]),
                    name=mgmt_iface,
                    iface_type=mgmt_iface_type,
                )
                ip = ensure_ip(client, mgmt_ip)
                assign_ip_to_interface(client, ip_id=int(ip["id"]), interface_id=int(iface["id"]))
                set_device_primary_ip4(client, device_id=int(dev["id"]), ip_id=int(ip["id"]))
                stats["ip_assigned"] += 1

            stats["processed"] += 1
            print(f"{name}: ensured (site={site_slug} role={role_name} type={model})")

        except Exception as exc:  # noqa: BLE001
            stats["errors"] += 1
            print(f"{name or '<missing name>'}: ERROR {exc}")

    print("\nSummary:")
    print(f"  processed:  {stats['processed']}")
    print(f"  ip_assigned:{stats['ip_assigned']}")
    print(f"  errors:     {stats['errors']}")
    return 0 if stats["errors"] == 0 else 5


if __name__ == "__main__":
    raise SystemExit(main())
