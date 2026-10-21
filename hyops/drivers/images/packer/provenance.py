"""Template build provenance for the Packer image driver."""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from hyops.runtime.module_state import read_module_state
from hyops.runtime.state import write_json_atomic


_MANIFEST_KEYS = (
    "schema_version",
    "run_id",
    "template_key",
    "template_name",
    "vmid",
    "source_filename",
    "source_url",
    "source_checksum",
    "profile",
    "pack_id",
    "builder_version",
)


def public_source_url(value: str) -> str | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    parsed = urlsplit(raw)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        return None
    host = parsed.hostname
    if ":" in host:
        host = f"[{host}]"
    if parsed.port:
        host = f"{host}:{parsed.port}"
    return urlunsplit((parsed.scheme, host, parsed.path or "", "", ""))


def source_filename(value: str) -> str:
    raw = str(value or "").strip()
    if not raw:
        return ""
    parsed = urlsplit(raw)
    path = parsed.path if parsed.scheme in {"http", "https"} else raw
    return Path(path).name


def parse_packer_version(text: str) -> str | None:
    for token in str(text or "").replace(",", " ").split():
        candidate = token.lstrip("vV")
        parts = candidate.split(".")
        if len(parts) >= 3 and all(part.isdigit() for part in parts[:3]):
            return ".".join(parts[:3])
    return None


def lookup_packer_version(binary: str) -> tuple[str | None, str]:
    warning = "packer version was not recognized; recorded builder_version as null"
    try:
        proc = subprocess.run(
            [binary, "version"],
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None, warning
    version = parse_packer_version(f"{proc.stdout}\n{proc.stderr}")
    if proc.returncode != 0 or not version:
        return None, warning
    return version, ""


def source_from_vars(base_vars: dict[str, Any], runtime_vars: dict[str, Any]) -> tuple[str, str]:
    url = str(runtime_vars.get("iso_url") or base_vars.get("iso_url") or "").strip()
    checksum = str(runtime_vars.get("iso_checksum") or base_vars.get("iso_checksum") or "").strip()
    return url, checksum


def build_template_manifest(
    *,
    run_id: str,
    template_key: str,
    template_name: str,
    vmid: int,
    source_url: str,
    source_checksum: str,
    profile: str,
    pack_id: str,
    builder_version: str | None,
) -> dict[str, Any]:
    manifest = {
        "schema_version": 1,
        "run_id": run_id,
        "template_key": template_key,
        "template_name": template_name,
        "vmid": int(vmid),
        "source_filename": source_filename(source_url),
        "source_url": public_source_url(source_url),
        "source_checksum": str(source_checksum or ""),
        "profile": profile,
        "pack_id": pack_id,
        "builder_version": builder_version or None,
    }
    return {key: manifest[key] for key in _MANIFEST_KEYS}


def write_template_manifest(evidence_dir: Path, manifest: dict[str, Any]) -> Path:
    path = Path(evidence_dir) / "template_manifest.json"
    write_json_atomic(path, manifest, mode=0o600)
    return path


def retained_provenance(record: dict[str, Any] | None) -> dict[str, str]:
    if not isinstance(record, dict):
        return {}
    kept: dict[str, str] = {}
    for key in ("source_checksum", "build_run_id"):
        value = record.get(key)
        if isinstance(value, str) and value.strip():
            kept[key] = value.strip()
    return kept


def previous_template_provenance(
    *,
    state_dir: str,
    module_ref: str,
    template_key: str,
    state_instance: str | None,
) -> dict[str, str]:
    root = str(state_dir or "").strip()
    ref = str(module_ref or "").strip()
    key = str(template_key or "").strip()
    if not root or not ref or not key:
        return {}
    try:
        state = read_module_state(Path(root), ref, state_instance=state_instance or None)
    except (OSError, ValueError):
        return {}
    outputs = state.get("outputs")
    if not isinstance(outputs, dict):
        return {}
    templates = outputs.get("templates")
    if not isinstance(templates, dict):
        return {}
    record = templates.get(key)
    return retained_provenance(record if isinstance(record, dict) else None)
