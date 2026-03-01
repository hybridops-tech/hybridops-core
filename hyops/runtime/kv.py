"""Simple KEY=VALUE config parsing.

purpose: Shared parser for HyOps init/runtime config files.
Architecture Decision: ADR-N/A
maintainer: HybridOps.Studio
"""

from __future__ import annotations

from pathlib import Path


def read_kv_file(path: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        out[key.strip()] = value.strip().strip('"').strip("'")
    return out


__all__ = ["read_kv_file"]
