# purpose: Read/merge/write infrastructure.csv while preserving exporter-specific metadata columns.
# adr: ADR-0002_source-of-truth_netbox-driven-inventory
# maintainer: HybridOps.Studio

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any


def _as_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    return str(value)


def _stringify_for_csv(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, (int, float, bool)):
        return str(value)
    if isinstance(value, (list, dict)):
        return json.dumps(value, separators=(",", ":"), sort_keys=True)
    return str(value)


def read_csv(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    if not path.exists():
        return [], []

    with path.open("r", newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        header = list(reader.fieldnames or [])
        rows: list[dict[str, str]] = []
        for r in reader:
            rows.append({k: (v or "") for k, v in r.items()})
        return header, rows


def ensure_header(existing: list[str], required: list[str], optional: list[str]) -> list[str]:
    header: list[str] = []
    seen: set[str] = set()

    def _add(field: str) -> None:
        if field and field not in seen:
            seen.add(field)
            header.append(field)

    for f in existing:
        _add(f)

    for f in required:
        _add(f)

    for f in optional:
        _add(f)

    return header


def merge_rows_by_preferred_keys(
    *,
    existing: list[dict[str, Any]],
    new: list[dict[str, Any]],
    keys: list[str],
) -> list[dict[str, Any]]:
    def _row_key(row: dict[str, Any], fallback: str) -> str:
        for k in keys:
            v = _as_text(row.get(k)).strip()
            if v:
                return f"{k}={v}"
        return fallback

    by_key: dict[str, dict[str, Any]] = {}

    for idx, r in enumerate(existing):
        rk = _row_key(r, fallback=f"__existing__:{idx}")
        by_key[rk] = dict(r)

    for idx, r in enumerate(new):
        rk = _row_key(r, fallback=f"__new__:{idx}")
        merged = dict(by_key.get(rk, {}))

        for kk, vv in r.items():
            if vv is None:
                continue
            if isinstance(vv, str) and vv == "":
                continue
            merged[kk] = vv

        by_key[rk] = merged

    return list(by_key.values())




def merge_rows_by_key(
    *,
    existing: list[dict[str, Any]],
    new: list[dict[str, Any]],
    key: str,
) -> list[dict[str, Any]]:
    return merge_rows_by_preferred_keys(existing=existing, new=new, keys=[key])


def write_csv(path: Path, header: list[str], rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)

    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=header, extrasaction="ignore")
        writer.writeheader()
        for r in rows:
            writer.writerow({k: _stringify_for_csv(r.get(k)) for k in header})
