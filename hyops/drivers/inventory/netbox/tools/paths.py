#!/usr/bin/env python3
# purpose: Shared path resolution for NetBox export/import tooling in HybridOps.Core.
# maintainer: HybridOps.Tech

from __future__ import annotations

import os
from pathlib import Path
from typing import Final


def _resolve_root() -> Path:
    raw_root = os.environ.get("HYOPS_NETBOX_ROOT", "").strip()
    if raw_root:
        p = Path(raw_root).expanduser()
        return p if p.is_absolute() else (Path.cwd() / p).resolve()

    runtime_raw = os.environ.get("HYOPS_RUNTIME_ROOT", "").strip()
    if runtime_raw:
        p = Path(runtime_raw).expanduser()
        return p if p.is_absolute() else (Path.cwd() / p).resolve()

    return Path.cwd().resolve()


RUNTIME_ROOT: Final[Path] = _resolve_root()


def _resolve_from_root(env_var: str, default_rel: str) -> Path:
    raw = os.environ.get(env_var, "").strip()
    if not raw:
        return (RUNTIME_ROOT / default_rel).resolve()

    p = Path(raw).expanduser()
    return p if p.is_absolute() else (RUNTIME_ROOT / p).resolve()


def control_secrets_env_path() -> Path:
    return _resolve_from_root("CONTROL_SECRETS_ENV", "credentials/netbox.env")


def vms_auto_csv_path() -> Path:
    return _resolve_from_root("NETBOX_VMS_AUTO_CSV", "state/netbox/vms/vms.auto.csv")


def vms_auto_json_path() -> Path:
    return _resolve_from_root("NETBOX_VMS_AUTO_JSON", "state/netbox/vms/vms.auto.json")


def devices_manual_csv_path() -> Path:
    return _resolve_from_root("NETBOX_DEVICES_MANUAL_CSV", "state/netbox/devices/devices.manual.csv")


def sdn_terragrunt_dir_path() -> Path:
    return _resolve_from_root("NETBOX_SDN_TERRAGRUNT_DIR", "work/stack")


def ipam_prefixes_emit_csv_path() -> Path:
    return _resolve_from_root("NETBOX_IPAM_PREFIXES_EMIT_CSV", "state/netbox/network/ipam-prefixes.csv")


def ipam_prefixes_emit_json_path() -> Path:
    return _resolve_from_root("NETBOX_IPAM_PREFIXES_EMIT_JSON", "state/netbox/network/ipam-prefixes.json")


def ipam_prefixes_auto_csv_path() -> Path:
    return _resolve_from_root("NETBOX_IPAM_PREFIXES_AUTO_CSV", "state/netbox/network/ipam-prefixes.auto.csv")


def ipam_prefixes_auto_json_path() -> Path:
    return _resolve_from_root("NETBOX_IPAM_PREFIXES_AUTO_JSON", "state/netbox/network/ipam-prefixes.auto.json")
