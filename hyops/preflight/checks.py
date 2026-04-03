"""Preflight checks.

purpose: Provide small, composable checks for tool presence and runtime readiness.
maintainer: HybridOps.Tech
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import shutil


@dataclass(frozen=True)
class CheckResult:
    name: str
    ok: bool
    detail: str = ""


def which(cmd: str) -> str | None:
    return shutil.which(cmd)


def file_exists(path: Path) -> bool:
    try:
        return path.exists()
    except Exception:
        return False


def is_mode_0600(path: Path) -> bool:
    try:
        return (path.stat().st_mode & 0o777) == 0o600
    except Exception:
        return False
