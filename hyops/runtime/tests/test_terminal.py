"""Tests for terminal status styling."""

from __future__ import annotations

import io
import os
import unittest
from unittest.mock import patch

from hyops.runtime.command_evidence import _TeeStream
from hyops.runtime.terminal import (
    StatusStream,
    colour_enabled,
    decorate_status_text,
)


class _Stream(io.StringIO):
    def __init__(self, tty: bool) -> None:
        super().__init__()
        self.tty = tty

    def isatty(self) -> bool:
        return self.tty


class TerminalStatusTests(unittest.TestCase):
    def test_tty_status_tokens_are_coloured(self) -> None:
        rendered = decorate_status_text(
            "ok      runtime:root\nstatus=ready\nERR: failed\n",
            enabled=True,
        )

        self.assertIn("\033[32mok\033[0m", rendered)
        self.assertIn("status=\033[32mready\033[0m", rendered)
        self.assertIn("\033[31mERR:\033[0m", rendered)

    def test_no_color_disables_terminal_colours(self) -> None:
        stream = _Stream(True)
        with patch.dict(os.environ, {"NO_COLOR": ""}):
            self.assertFalse(colour_enabled(stream))

    def test_non_tty_disables_terminal_colours(self) -> None:
        self.assertFalse(colour_enabled(_Stream(False)))

    def test_run_record_remains_plain(self) -> None:
        terminal = _Stream(True)
        record = io.StringIO()
        tee = _TeeStream(StatusStream(terminal), record)

        with patch.dict(os.environ, {"TERM": "xterm"}):
            os.environ.pop("NO_COLOR", None)
            tee.write("ok      runtime:root\nERR: failed\n")

        self.assertIn("\033[32m", terminal.getvalue())
        self.assertIn("\033[31m", terminal.getvalue())
        self.assertNotIn("\033[", record.getvalue())
        self.assertEqual(
            record.getvalue(),
            "ok      runtime:root\nERR: failed\n",
        )


if __name__ == "__main__":
    unittest.main()
