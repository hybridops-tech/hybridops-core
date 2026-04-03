"""Init target helpers.

purpose: Centralize shared init run-id, evidence dir, and config parsing helpers.
maintainer: HybridOps.Tech
"""

from __future__ import annotations

from pathlib import Path

from hyops.runtime.kv import read_kv_file
from hyops.runtime.evidence import init_evidence_dir, new_run_id


def init_run_id(prefix: str) -> str:
    return new_run_id(prefix)


def init_evidence_path(root: Path, out_dir: str | None, target: str, run_id: str) -> Path:
    if out_dir:
        base = Path(out_dir).expanduser().resolve() / "init" / target
    else:
        base = root / "logs" / "init" / target
    return init_evidence_dir(base, run_id)


__all__ = ["init_run_id", "init_evidence_path", "read_kv_file"]
