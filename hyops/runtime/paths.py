"""
Canonical runtime paths.

purpose: Provide deterministic paths for runtime layout with overrides.
Architecture Decision: ADR-N/A (runtime paths)
maintainer: HybridOps.Studio
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from hyops.runtime.root import resolve_runtime_root


@dataclass(frozen=True)
class RuntimePaths:
    root: Path
    config_dir: Path
    credentials_dir: Path
    vault_dir: Path
    state_dir: Path
    logs_dir: Path
    meta_dir: Path
    work_dir: Path

    @staticmethod
    def from_root(root: Path) -> "RuntimePaths":
        root = root.expanduser().resolve()
        return RuntimePaths(
            root=root,
            config_dir=root / "config",
            credentials_dir=root / "credentials",
            vault_dir=root / "vault",
            state_dir=root / "state",
            logs_dir=root / "logs",
            meta_dir=root / "meta",
            work_dir=root / "work",
        )


def resolve_runtime_paths(root: str | None = None, env: str | None = None) -> RuntimePaths:
    return RuntimePaths.from_root(resolve_runtime_root(root, env))
