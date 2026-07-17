"""Concise terminal progress without changing execution or run-record capture."""

from __future__ import annotations

import os
import sys
import threading
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
    show_elapsed: bool = True
    _started: dict[str, float] = field(default_factory=dict)
    _labels: dict[str, str] = field(default_factory=dict)
    _stops: dict[str, threading.Event] = field(default_factory=dict)
    _threads: dict[str, threading.Thread] = field(default_factory=dict)

    def _animate(self, key: str, label: str, stopped: threading.Event) -> None:
        frames = ("|", "/", "-", "\\")
        frame = 0
        while not stopped.wait(0.2):
            started = self._started.get(key, time.monotonic())
            current_label = self._labels.get(key, label)
            elapsed = f"  {_elapsed(started)}" if self.show_elapsed else ""
            print(f"\r\033[2K{frames[frame]} {current_label}{elapsed}", end="", flush=True)
            frame = (frame + 1) % len(frames)

    def start(self, key: str, label: str, *, plain: str) -> None:
        self._started[key] = time.monotonic()
        self._labels[key] = label
        if self.enabled:
            elapsed = "  0s" if self.show_elapsed else ""
            print(f"| {label}{elapsed}", end="", flush=True)
            stopped = threading.Event()
            thread = threading.Thread(
                target=self._animate,
                args=(key, label, stopped),
                daemon=True,
            )
            self._stops[key] = stopped
            self._threads[key] = thread
            thread.start()
        else:
            print(plain, flush=True)

    def update(self, key: str, label: str) -> None:
        """Update an active interactive label without adding terminal output."""
        if self.enabled and key in self._started:
            self._labels[key] = label

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
        self._labels.pop(key, None)
        if started is None:
            started = time.monotonic()
        if not self.enabled:
            print(plain, flush=True)
            return
        stopped = self._stops.pop(key, None)
        if stopped is not None:
            stopped.set()
        thread = self._threads.pop(key, None)
        if thread is not None:
            thread.join(timeout=1)
        symbol = {
            "ok": "✓",
            "skipped": "○",
            "retained": "○",
            "cancelled": "!",
            "failed-optional": "!",
        }.get(status, "✗")
        suffix = f"  {_elapsed(started)}" if self.show_elapsed else ""
        if detail:
            suffix += f"  {detail}"
        print(f"\r\033[2K{symbol} {label}{suffix}", flush=True)
