"""GCP public-price estimation for deployed Compute Engine VMs."""

from __future__ import annotations

import json
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request
from decimal import Decimal
from pathlib import Path
from typing import Any

import yaml

from hyops.runtime.cost import CostEstimate

_COMPUTE_SERVICE = "services/6F81-5844-456A"
_HOURS_PER_MONTH = Decimal("730")


def _capture(argv: list[str]) -> tuple[int, str, str]:
    try:
        proc = subprocess.run(argv, text=True, capture_output=True, check=False)
    except OSError as exc:
        return 127, "", str(exc)
    return proc.returncode, str(proc.stdout or "").strip(), str(proc.stderr or "").strip()


def _read_inputs(state: dict[str, Any]) -> dict[str, Any]:
    raw = str(state.get("rerun_inputs_file") or "").strip()
    if not raw:
        return {}
    path = Path(raw).expanduser()
    if not path.is_file():
        return {}
    payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return payload if isinstance(payload, dict) else {}


def _access_token() -> tuple[str, str]:
    rc, stdout, stderr = _capture(
        ["gcloud", "auth", "application-default", "print-access-token"]
    )
    if rc != 0 or not stdout:
        return "", stderr or "application credentials are unavailable"
    return stdout, ""


def _public_compute_skus(
    token: str,
    currency: str,
    *,
    region: str = "",
    cache_file: Path | None = None,
) -> tuple[list[dict[str, Any]], str]:
    if cache_file and cache_file.is_file():
        try:
            if time.time() - cache_file.stat().st_mtime < 86400:
                cached = json.loads(cache_file.read_text(encoding="utf-8"))
                if isinstance(cached, list):
                    return [item for item in cached if isinstance(item, dict)], ""
        except (OSError, json.JSONDecodeError):
            pass
    all_skus: list[dict[str, Any]] = []
    page_token = ""
    while True:
        params = {"pageSize": 5000, "currencyCode": currency}
        if page_token:
            params["pageToken"] = page_token
        query = urllib.parse.urlencode(params)
        url = f"https://cloudbilling.googleapis.com/v1/{_COMPUTE_SERVICE}/skus?{query}"
        req = urllib.request.Request(
            url,
            headers={"Authorization": f"Bearer {token}"},
            method="GET",
        )
        try:
            with urllib.request.urlopen(req, timeout=20) as response:
                payload = json.loads(response.read().decode("utf-8") or "{}")
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace").strip()
            return [], f"pricing service returned HTTP {exc.code}: {detail or exc.reason}"
        except Exception as exc:
            return [], str(exc)
        skus = payload.get("skus")
        if not isinstance(skus, list):
            return [], "pricing service returned no Compute Engine SKUs"
        all_skus.extend(item for item in skus if isinstance(item, dict))
        page_token = str(payload.get("nextPageToken") or "").strip()
        if not page_token:
            if region:
                all_skus = [
                    sku
                    for sku in all_skus
                    if region in (sku.get("serviceRegions") or [])
                    and (sku.get("category") or {}).get("usageType") == "OnDemand"
                ]
            if cache_file:
                try:
                    cache_file.parent.mkdir(parents=True, exist_ok=True)
                    cache_file.write_text(json.dumps(all_skus), encoding="utf-8")
                except OSError:
                    pass
            return all_skus, ""


def _unit_price(sku: dict[str, Any]) -> tuple[Decimal, str]:
    pricing = sku.get("pricingInfo")
    if not isinstance(pricing, list) or not pricing:
        return Decimal("0"), ""
    expression = pricing[0].get("pricingExpression")
    if not isinstance(expression, dict):
        return Decimal("0"), ""
    rates = expression.get("tieredRates")
    if not isinstance(rates, list) or not rates:
        return Decimal("0"), ""
    unit = rates[0].get("unitPrice")
    if not isinstance(unit, dict):
        return Decimal("0"), ""
    amount = Decimal(str(unit.get("units") or 0))
    amount += Decimal(str(unit.get("nanos") or 0)) / Decimal(1_000_000_000)
    return amount, str(expression.get("usageUnit") or "")


def _matching_price(
    skus: list[dict[str, Any]],
    *,
    region: str,
    resource_group: str,
    description_terms: tuple[str, ...],
    excluded_terms: tuple[str, ...] = (),
) -> tuple[Decimal, str]:
    for sku in skus:
        category = sku.get("category")
        if not isinstance(category, dict):
            continue
        regions = sku.get("serviceRegions")
        description = str(sku.get("description") or "").lower()
        if (
            str(category.get("usageType") or "") != "OnDemand"
            or str(category.get("resourceGroup") or "") != resource_group
            or any(term.lower() not in description for term in description_terms)
            or any(term.lower() in description for term in excluded_terms)
            or not isinstance(regions, list)
            or region not in regions
        ):
            continue
        price, unit = _unit_price(sku)
        if price:
            return price, unit
    return Decimal("0"), ""


def _machine_shape(project_id: str, zone: str, machine_type: str) -> tuple[int, Decimal, str]:
    rc, stdout, stderr = _capture(
        [
            "gcloud",
            "compute",
            "machine-types",
            "describe",
            machine_type,
            "--project",
            project_id,
            "--zone",
            zone,
            "--format=json",
        ]
    )
    if rc != 0:
        return 0, Decimal("0"), stderr or "machine shape could not be resolved"
    try:
        payload = json.loads(stdout)
        cpus = int(payload["guestCpus"])
        memory_gib = Decimal(str(payload["memoryMb"])) / Decimal(1024)
    except (KeyError, TypeError, ValueError, json.JSONDecodeError):
        return 0, Decimal("0"), "machine shape response was invalid"
    return cpus, memory_gib, ""


def estimate_gcp_vm_cost(
    *,
    project_id: str,
    zone: str,
    state: dict[str, Any],
    currency: str = "USD",
    cache_dir: Path | None = None,
) -> CostEstimate:
    """Estimate fixed hourly VM and persistent-disk charges from deployed state."""

    inputs = _read_inputs(state)
    machine_type = str(inputs.get("machine_type") or "").strip()
    disk_type = str(inputs.get("boot_disk_type") or "").strip()
    try:
        disk_gib = Decimal(str(inputs.get("boot_disk_size_gb") or 0))
    except Exception:
        disk_gib = Decimal("0")
    if not machine_type or not disk_type or disk_gib <= 0:
        return CostEstimate(False, detail="deployed VM pricing inputs are unavailable")

    cpus, memory_gib, detail = _machine_shape(project_id, zone, machine_type)
    if detail:
        return CostEstimate(False, detail=detail)
    token, detail = _access_token()
    if detail:
        return CostEstimate(False, detail=detail)
    region = zone.rsplit("-", 1)[0]
    cache_file = (
        cache_dir / f"gcp-compute-prices-{region}-{currency.lower()}.json"
        if cache_dir
        else None
    )
    skus, detail = _public_compute_skus(
        token,
        currency,
        region=region,
        cache_file=cache_file,
    )
    if detail:
        return CostEstimate(False, detail=detail)

    family = machine_type.split("-", 1)[0].upper()
    core_price, core_unit = _matching_price(
        skus,
        region=region,
        resource_group="CPU",
        description_terms=(f"{family} instance", "core"),
    )
    ram_price, ram_unit = _matching_price(
        skus,
        region=region,
        resource_group="RAM",
        description_terms=(f"{family} instance", "ram"),
    )
    disk_groups = {
        "pd-standard": "PDStandard",
        "pd-balanced": "PDBalanced",
        "pd-ssd": "SSD",
    }
    disk_price, disk_unit = _matching_price(
        skus,
        region=region,
        resource_group=disk_groups.get(disk_type, ""),
        description_terms=("storage",),
        excluded_terms=("regional",),
    )
    if not core_price or not ram_price or not disk_price:
        return CostEstimate(False, detail="a public price was not found for the deployed VM shape")

    compute_hourly = core_price * cpus + ram_price * memory_gib
    disk_hourly = disk_price * disk_gib
    if "mo" in disk_unit.lower():
        disk_hourly /= _HOURS_PER_MONTH
    if "h" not in core_unit.lower() or "h" not in ram_unit.lower():
        return CostEstimate(False, detail="the public compute price used an unsupported unit")
    hourly = (compute_hourly + disk_hourly).quantize(Decimal("0.0001"))
    return CostEstimate(
        True,
        hourly=hourly,
        currency=currency,
        basis="public list price; usage-based network charges excluded",
    )
