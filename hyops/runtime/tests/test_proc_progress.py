"""Progress behaviour for captured subprocesses."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from hyops.runtime import proc


class _ImmediateTimer:
    def __init__(self, _interval, callback):
        self.callback = callback
        self.daemon = False

    def start(self) -> None:
        self.callback()

    def cancel(self) -> None:
        return None


class CapturedProcessProgressTests(unittest.TestCase):
    def test_quick_capture_does_not_start_progress_outside_tty(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, patch.object(
            proc, "concise_enabled", return_value=False
        ), patch.object(proc, "ProgressDisplay") as display:
            result = proc.run_capture(
                ["bash", "-lc", "printf ok"],
                evidence_dir=Path(tmp),
                label="quick_probe",
            )

        self.assertEqual(result.rc, 0)
        display.assert_not_called()

    def test_long_capture_finishes_delayed_progress(self) -> None:
        display = MagicMock()
        display.enabled = True
        with patch.object(proc, "concise_enabled", return_value=True), patch.object(
            proc.threading, "Timer", _ImmediateTimer
        ), patch.object(proc, "ProgressDisplay", return_value=display):
            result = proc._run_with_delayed_progress(
                ["bash", "-lc", "exit 0"],
                label="project_lookup",
                cwd=None,
                env=None,
                timeout_s=None,
            )

        self.assertEqual(result.rc, 0)
        display.start.assert_called_once()
        display.finish.assert_called_once()


if __name__ == "__main__":
    unittest.main()
