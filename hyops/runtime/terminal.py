"""Terminal status styling with plain non-interactive output."""

from __future__ import annotations

import os
import re
import sys
from typing import IO


RESET = "\033[0m"
COLOURS = {
    "success": "\033[32m",
    "warning": "\033[33m",
    "error": "\033[31m",
    "active": "\033[36m",
    "muted": "\033[2m",
}


def colour_enabled(stream: IO[str] | None = None) -> bool:
    stream = stream or sys.stdout
    if "NO_COLOR" in os.environ:
        return False
    if str(os.environ.get("TERM") or "").strip().lower() == "dumb":
        return False
    try:
        return bool(stream.isatty())
    except (AttributeError, OSError):
        return False


def style(text: str, tone: str, *, enabled: bool = True) -> str:
    if not enabled or not text:
        return text
    colour = COLOURS.get(tone)
    if not colour:
        return text
    return f"{colour}{text}{RESET}"


def decorate_status_text(text: str, *, enabled: bool) -> str:
    """Colour stable status tokens without changing their plain representation."""
    if not enabled or not text or "\033[" in text:
        return text

    decorated = re.sub(
        r"(?m)^(\s*)(ERR:|ERROR:)",
        lambda match: f"{match.group(1)}{style(match.group(2), 'error')}",
        text,
    )
    decorated = re.sub(
        r"(?m)^(\s*)(WARN:)",
        lambda match: f"{match.group(1)}{style(match.group(2), 'warning')}",
        decorated,
    )
    decorated = re.sub(
        r"(?m)^(\s*)(ok|ready)(?=\s|$)",
        lambda match: f"{match.group(1)}{style(match.group(2), 'success')}",
        decorated,
    )
    decorated = re.sub(
        r"(?m)^(\s*)(fail|failed|missing)(?=\s|$)",
        lambda match: f"{match.group(1)}{style(match.group(2), 'error')}",
        decorated,
    )
    decorated = re.sub(
        r"(?<=status=)(ok|ready)(?=\s|$)",
        lambda match: style(match.group(1), "success"),
        decorated,
    )
    decorated = re.sub(
        r"(?<=status=)(failed|error|not-ready)(?=\s|$)",
        lambda match: style(match.group(1), "error"),
        decorated,
    )
    decorated = re.sub(
        r"(?<=preflight_status=)(ok|ready)(?=\s|$)",
        lambda match: style(match.group(1), "success"),
        decorated,
    )
    decorated = re.sub(
        r"(?<=preflight_status=)(failed|error)(?=\s|$)",
        lambda match: style(match.group(1), "error"),
        decorated,
    )
    return decorated


class StatusStream:
    """Decorate terminal writes while retaining the wrapped stream contract."""

    def __init__(self, stream: IO[str]) -> None:
        self.stream = stream

    def write(self, text: str) -> int:
        rendered = decorate_status_text(
            text,
            enabled=colour_enabled(self.stream),
        )
        self.stream.write(rendered)
        return len(text)

    def flush(self) -> None:
        self.stream.flush()

    def isatty(self) -> bool:
        return self.stream.isatty()

    def fileno(self) -> int:
        return self.stream.fileno()

    def __getattr__(self, name: str):
        return getattr(self.stream, name)


def configure_status_streams() -> None:
    if not isinstance(sys.stdout, StatusStream):
        sys.stdout = StatusStream(sys.stdout)  # type: ignore[assignment]
    if not isinstance(sys.stderr, StatusStream):
        sys.stderr = StatusStream(sys.stderr)  # type: ignore[assignment]
