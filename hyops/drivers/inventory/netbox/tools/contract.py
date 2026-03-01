# purpose: Define the infrastructure.csv minimum contract shared by exporters and importers.
# adr: ADR-0002_source-of-truth_netbox-driven-inventory
# maintainer: HybridOps.Studio

from __future__ import annotations

from typing import Final

REQUIRED_FIELDS: Final[list[str]] = ["name", "ip_address", "cluster"]

OPTIONAL_FIELDS: Final[list[str]] = [
    "interface",
    "role",
    "status",
    "tags",
    "source",
    "external_id",
    "tf_address",
    "asset_tag",
    "serial",
    "mac_address",
    "ip_private",
    "ip_assignment",
    "vm_id",
    "cpu_cores",
    "memory_mb",
    "disk_gb",
]

DEFAULT_INTERFACE: Final[str] = "eth0"
DEFAULT_STATUS: Final[str] = "active"
