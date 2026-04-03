# purpose: Persist non-secret runtime metadata for operator debugging and auditability.
# maintainer: HybridOps.Tech

from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Any

from hyops.runtime.state import write_json_atomic


def stamp_runtime(
    root: Path,
    *,
    command: str,
    target: str | None,
    run_id: str | None,
    evidence_dir: Path | None,
    extra: dict[str, Any] | None = None,
) -> None:
    payload: dict[str, Any] = {
        "timestamp_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "root": str(root),
        "command": command,
        "target": target or "",
        "run_id": run_id or "",
        "evidence_dir": str(evidence_dir) if evidence_dir else "",
        "pid": os.getpid(),
    }
    if extra:
        payload["extra"] = extra

    write_json_atomic(root / "meta" / "runtime.json", payload, mode=0o600)