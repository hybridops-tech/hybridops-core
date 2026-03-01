"""
purpose: Create deterministic evidence directories and write structured artifacts.
Architecture Decision: ADR-N/A (evidence services)
maintainer: HybridOps.Studio
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
import secrets

from hyops.runtime.layout import ensure_parent
from hyops.runtime.redact import redact_text
from hyops.runtime.state import write_json_atomic


def new_run_id(prefix: str) -> str:
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return f"{prefix}-{ts}-{secrets.token_hex(4)}"


def init_evidence_dir(root: Path, run_id: str) -> Path:
    d = root / run_id
    ensure_parent(d)
    d.mkdir(parents=True, exist_ok=True)
    return d


@dataclass(frozen=True)
class EvidenceWriter:
    dir: Path

    def write_json(self, name: str, obj: Any, mode: int = 0o600) -> Path:
        p = self.dir / name
        write_json_atomic(p, obj, mode=mode)
        return p

    def write_text(self, name: str, text: str, redact_output: bool = True, mode: int = 0o600) -> Path:
        p = self.dir / name
        payload = redact_text(text) if redact_output else text
        p.write_text(payload, encoding="utf-8")
        p.chmod(mode)
        return p
