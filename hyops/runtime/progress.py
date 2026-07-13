"""Concise terminal progress without changing execution or run-record capture."""

from __future__ import annotations

import os
import sys
import time
from dataclasses import dataclass, field


def verbose_enabled() -> bool:
    return str(os.getenv("HYOPS_VERBOSE") or "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def concise_enabled() -> bool:
    return bool(sys.stdout and sys.stdout.isatty() and not verbose_enabled())


def _elapsed(started: float) -> str:
    seconds = max(0, int(time.monotonic() - started))
    minutes, seconds = divmod(seconds, 60)
    return f"{minutes}m {seconds:02d}s" if minutes else f"{seconds}s"


@dataclass
class ProgressDisplay:
    """Render stable plain output or concise interactive status lines."""

    enabled: bool = field(default_factory=concise_enabled)
    _started: dict[str, float] = field(default_factory=dict)

    def start(self, key: str, label: str, *, plain: str) -> None:
        self._started[key] = time.monotonic()
        if self.enabled:
            print(f"… {label}", flush=True)
        else:
            print(plain, flush=True)

    def finish(
        self,
        key: str,
        label: str,
        status: str,
        *,
        plain: str,
        detail: str = "",
    ) -> None:
        started = self._started.pop(key, None)
        if started is None:
            started = time.monotonic()
        if not self.enabled:
            print(plain, flush=True)
            return
        symbol = {
            "ok": "✓",
            "skipped": "○",
            "retained": "○",
            "cancelled": "!",
            "failed-optional": "!",
        }.get(status, "✗")
        suffix = f"  {_elapsed(started)}"
        if detail:
            suffix += f"  {detail}"
        print(f"{symbol} {label}{suffix}", flush=True)
