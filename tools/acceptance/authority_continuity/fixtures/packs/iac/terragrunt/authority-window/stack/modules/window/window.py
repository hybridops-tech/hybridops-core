"""Open and release one file-backed operation barrier."""

from __future__ import annotations

import json
import os
import re
import sys
import time
from pathlib import Path
from typing import Any

_NONCE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")


def _load_request(raw: str) -> tuple[Path, str, int]:
    try:
        payload: Any = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid barrier request: {exc}") from exc
    if not isinstance(payload, dict):
        raise TypeError("barrier request must be an object")

    unknown = sorted(set(payload) - {"barrier_dir", "run_nonce", "timeout_s"})
    if unknown:
        raise ValueError(f"unknown barrier request fields: {', '.join(unknown)}")

    raw_dir = str(payload.get("barrier_dir") or "").strip()
    barrier_dir = Path(raw_dir).expanduser()
    if not raw_dir or not barrier_dir.is_absolute():
        raise ValueError("barrier_dir must be an absolute path")
    if barrier_dir.is_symlink() or not barrier_dir.is_dir():
        raise ValueError("barrier_dir must be an existing non-symbolic-link directory")

    run_nonce = str(payload.get("run_nonce") or "").strip()
    if not _NONCE_RE.fullmatch(run_nonce):
        raise ValueError("run_nonce has an invalid format")

    timeout = payload.get("timeout_s")
    if isinstance(timeout, bool) or not isinstance(timeout, (int, float)):
        raise TypeError("timeout_s must be a whole number")
    timeout_s = int(timeout)
    if timeout_s != timeout or not 5 <= timeout_s <= 300:
        raise ValueError("timeout_s must be a whole number from 5 to 300")
    return barrier_dir, run_nonce, timeout_s


def _write_atomic(path: Path, payload: dict[str, Any]) -> None:
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(
        json.dumps(payload, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.chmod(0o600)
    os.replace(temporary, path)


def _release_matches(path: Path, run_nonce: str) -> bool:
    if not path.is_file():
        return False
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"invalid release marker: {exc}") from exc
    return isinstance(payload, dict) and payload.get("run_nonce") == run_nonce


def run(raw_request: str) -> int:
    barrier_dir, run_nonce, timeout_s = _load_request(raw_request)
    opened = barrier_dir / "window-open.json"
    released = barrier_dir / "window-release.json"
    if opened.exists() or released.exists():
        raise ValueError("barrier directory contains stale operation markers")

    _write_atomic(
        opened,
        {
            "kind": "hybridops/authority-window",
            "run_nonce": run_nonce,
            "status": "open",
        },
    )

    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if _release_matches(released, run_nonce):
            return 0
        time.sleep(0.05)
    raise TimeoutError(f"operation window was not released within {timeout_s} seconds")


def main() -> int:
    if len(sys.argv) != 2:
        print("ERR: expected one JSON barrier request", file=sys.stderr)
        return 2
    try:
        return run(sys.argv[1])
    except (OSError, TimeoutError, TypeError, ValueError) as exc:
        print(f"ERR: authority window failed: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
