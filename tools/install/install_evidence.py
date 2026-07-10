#!/usr/bin/env python3
"""Stream redacted installer output and write a small result record."""

from __future__ import annotations

from datetime import datetime, timezone
import json
import platform
from pathlib import Path
import sys

from hyops.runtime.redact import redact_text


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def stream(log_path: Path) -> int:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("a", encoding="utf-8") as log:
        log_path.chmod(0o600)
        for line in sys.stdin:
            safe_line = redact_text(line)
            sys.stdout.write(safe_line)
            sys.stdout.flush()
            log.write(safe_line)
            log.flush()
    return 0


def result(path: Path, started_at: str, exit_code: int, argv: list[str]) -> int:
    payload = {
        "command": "install",
        "argv": [redact_text(token) for token in argv],
        "started_at": started_at,
        "finished_at": _now(),
        "exit_code": exit_code,
        "status": "ok" if exit_code == 0 else "failed",
        "platform": {
            "system": platform.system(),
            "machine": platform.machine(),
            "python": platform.python_version(),
        },
    }
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    path.chmod(0o600)
    return 0


def main() -> int:
    if len(sys.argv) >= 3 and sys.argv[1] == "stream":
        return stream(Path(sys.argv[2]))
    if len(sys.argv) >= 5 and sys.argv[1] == "result":
        return result(Path(sys.argv[2]), sys.argv[3], int(sys.argv[4]), sys.argv[5:])
    print("usage: install_evidence.py stream <log> | result <json> <started> <code> [argv...]", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
