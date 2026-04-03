"""Readiness markers.

purpose: Read/write target readiness markers under the runtime meta directory.
maintainer: HybridOps.Tech
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from hyops.runtime.state import read_json, write_json_atomic


def marker_path(meta_dir: Path, target: str) -> Path:
    return meta_dir / f"{target}.ready.json"


def write_marker(meta_dir: Path, target: str, obj: dict[str, Any]) -> Path:
    p = marker_path(meta_dir, target)
    write_json_atomic(p, obj, mode=0o600)
    return p


def read_marker(meta_dir: Path, target: str) -> dict[str, Any]:
    return read_json(marker_path(meta_dir, target))
