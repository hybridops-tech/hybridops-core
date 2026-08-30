from __future__ import annotations

import io
from contextlib import redirect_stdout
from unittest import TestCase

from hyops.lab.command import _CaptureProgress


class CaptureProgressTest(TestCase):
    def test_non_tty_output_reports_assessment_heartbeat_and_completion(self) -> None:
        output = io.StringIO()
        with redirect_stdout(output):
            progress = _CaptureProgress()
            progress(
                {
                    "phase": "assessment_finished",
                    "primary_bytes": 4096,
                    "node_state_bytes": 8192,
                    "image_bytes": 16384,
                }
            )
            progress(
                {
                    "phase": "stream_started",
                    "stage": "node_state",
                    "expected_source_bytes": 8192,
                }
            )
            progress(
                {
                    "phase": "stream_progress",
                    "stage": "node_state",
                    "bytes_written": 2048,
                    "bytes_per_second": 64,
                    "elapsed_seconds": 31,
                }
            )
            progress(
                {
                    "phase": "stream_finished",
                    "stage": "node_state",
                    "status": "ok",
                    "bytes_written": 4096,
                    "bytes_per_second": 128,
                    "elapsed_seconds": 32,
                }
            )

        text = output.getvalue()
        self.assertIn("source assessment:", text)
        self.assertIn("capture=node_state status=running source_bytes=8192", text)
        self.assertIn("capture=node_state status=running bytes=2048", text)
        self.assertIn("capture=node_state status=ok bytes=4096", text)


if __name__ == "__main__":
    import unittest

    unittest.main()
