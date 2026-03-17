"""State persistence.

purpose: Read/write small JSON state files atomically (latest.json, readiness markers).
Architecture Decision: ADR-N/A (state)
maintainer: HybridOps.Tech
"""

from __future__ import annotations

from pathlib import Path
import json
import os
import tempfile
from typing import Any

import yaml


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json_atomic(path: Path, obj: Any, mode: int = 0o600) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(obj, indent=2, sort_keys=True) + "\n"
    fd, tmp = tempfile.mkstemp(prefix=path.name + ".", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(payload)
        os.chmod(tmp, mode)
        os.replace(tmp, path)
    finally:
        try:
            os.unlink(tmp)
        except FileNotFoundError:
            pass


def write_json(path: Path, obj: Any, mode: int = 0o600) -> None:
    write_json_atomic(path, obj, mode=mode)


def write_text_atomic(path: Path, text: str, mode: int = 0o600) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=path.name + ".", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
        os.chmod(tmp, mode)
        os.replace(tmp, path)
    finally:
        try:
            os.unlink(tmp)
        except FileNotFoundError:
            pass


def write_yaml_atomic(
    path: Path,
    obj: Any,
    *,
    mode: int = 0o600,
    sort_keys: bool = False,
) -> None:
    payload = yaml.safe_dump(obj, sort_keys=sort_keys)
    write_text_atomic(path, payload, mode=mode)
