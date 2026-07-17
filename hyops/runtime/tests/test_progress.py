"""Tests for terminal progress selection and stable output."""

from __future__ import annotations

import io
import os
import time
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

from hyops.runtime.progress import ProgressDisplay, concise_enabled


class _Stream(io.StringIO):
    def __init__(self, tty: bool) -> None:
        super().__init__()
        self.tty = tty

    def isatty(self) -> bool:
        return self.tty


class ProgressDisplayTests(unittest.TestCase):
    def test_non_tty_uses_stable_plain_lines(self) -> None:
        output = _Stream(False)
        display = ProgressDisplay(enabled=False)
        with redirect_stdout(output):
            display.start("network", "Network", plain="step=network status=running")
            display.finish("network", "Network", "ok", plain="step=network status=ok")
        self.assertEqual(
            output.getvalue().splitlines(),
            ["step=network status=running", "step=network status=ok"],
        )

    def test_tty_uses_concise_status(self) -> None:
        output = _Stream(True)
        display = ProgressDisplay(enabled=True)
        with redirect_stdout(output), patch.dict(
            os.environ, {"NO_COLOR": "1"}
        ), patch(
            "hyops.runtime.progress.time.monotonic", side_effect=[10.0, 15.0]
        ), patch.object(display, "_animate"):
            display.start("network", "Network", plain="ignored")
            display.finish("network", "Network", "ok", plain="ignored")
        self.assertEqual(
            output.getvalue(),
            "| Network  0s\r\x1b[2K✓ Network  5s\n",
        )

    def test_verbose_disables_concise_output(self) -> None:
        output = _Stream(True)
        with patch("hyops.runtime.progress.sys.stdout", output), patch.dict(
            os.environ, {"HYOPS_VERBOSE": "1"}
        ):
            self.assertFalse(concise_enabled())

    def test_tty_can_show_stage_percentage_without_elapsed_time(self) -> None:
        output = _Stream(True)
        display = ProgressDisplay(enabled=True, show_elapsed=False)
        with redirect_stdout(output), patch.dict(
            os.environ, {"NO_COLOR": "1"}
        ), patch.object(display, "_animate"):
            display.start("network", "Network  overall 0%", plain="ignored")
            display.finish(
                "network",
                "Network",
                "ok",
                plain="ignored",
                detail="overall 20%",
            )

        self.assertEqual(
            output.getvalue(),
            "| Network  overall 0%\r\x1b[2K✓ Network  overall 20%\n",
        )

    def test_tty_label_can_be_updated(self) -> None:
        output = _Stream(True)
        display = ProgressDisplay(enabled=True)
        with redirect_stdout(output), patch(
            "hyops.runtime.progress.time.monotonic", side_effect=[10.0, 15.0]
        ), patch.object(display, "_animate"):
            display.start("base", "Base tools", plain="ignored")
            display.update("base", "Base tools: Preparing system packages")
            self.assertEqual(
                display._labels["base"],
                "Base tools: Preparing system packages",
            )
            display.finish("base", "Base tools", "ok", plain="ignored")

    def test_tracked_percentage_advances_without_crossing_boundary(self) -> None:
        display = ProgressDisplay(enabled=True, show_elapsed=False)
        display._started["galaxy"] = time.monotonic()
        display._labels["galaxy"] = "Galaxy dependencies  43%"
        display.track_percent(
            "galaxy",
            "Galaxy dependencies",
            current=43,
            ceiling=45,
            interval_s=1,
        )
        tracked = display._percent_tracks["galaxy"]
        first_tick = float(tracked["last_advance"]) + 1.1

        display._advance_tracked_percent("galaxy", now=first_tick)
        display._advance_tracked_percent("galaxy", now=first_tick + 1.1)
        display._advance_tracked_percent("galaxy", now=first_tick + 2.2)

        self.assertEqual(display._labels["galaxy"], "Galaxy dependencies  45%")


if __name__ == "__main__":
    unittest.main()
