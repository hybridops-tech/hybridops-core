"""Runtime directory layout.

purpose: Create and validate `~/.hybridops` layout with secure permissions.
Architecture Decision: ADR-N/A (runtime layout)
maintainer: HybridOps.Tech
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import os


@dataclass(frozen=True)
class LayoutResult:
    created: list[Path]
    ensured: list[Path]


def _ensure_dir(path: Path, mode: int) -> bool:
    if path.exists():
        if not path.is_dir():
            raise RuntimeError(f"Path exists but is not a directory: {path}")
        return False
    path.mkdir(parents=True, exist_ok=True)
    os.chmod(path, mode)
    return True


def ensure_layout(paths) -> LayoutResult:
    created: list[Path] = []
    ensured: list[Path] = []
    for d in [
        paths.root,
        paths.config_dir,
        paths.credentials_dir,
        paths.vault_dir,
        paths.state_dir,
        paths.logs_dir,
        paths.meta_dir,
        paths.work_dir,
    ]:
        made = _ensure_dir(d, 0o700)
        (created if made else ensured).append(d)
    return LayoutResult(created=created, ensured=ensured)


def ensure_parent(path: Path, mode: int = 0o700) -> None:
    parent = path.parent
    if not parent.exists():
        parent.mkdir(parents=True, exist_ok=True)
        os.chmod(parent, mode)


def ensure_runtime_layout(root: Path) -> LayoutResult:
    from hyops.runtime.paths import resolve_runtime_paths
    return ensure_layout(resolve_runtime_paths(str(root)))
