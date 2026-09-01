from __future__ import annotations

import io
from contextlib import redirect_stdout
from unittest import TestCase

from hyops.lab.command import _CaptureProgress, _ImportProgress


class CaptureProgressTest(TestCase):
    def test_non_tty_output_reports_assessment_heartbeat_and_completion(self) -> None:
        output = io.StringIO()
        with redirect_stdout(output):
            progress = _CaptureProgress()
            self.assertFalse(progress.display.show_elapsed)
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


class ImportProgressTest(TestCase):
    def test_non_tty_output_reports_verification_copy_and_completion(self) -> None:
        output = io.StringIO()
        with redirect_stdout(output):
            progress = _ImportProgress()
            self.assertFalse(progress.display.show_elapsed)
            progress({"phase": "import_verification_started"})
            progress(
                {
                    "phase": "import_verification_finished",
                    "status": "ok",
                }
            )
            progress(
                {
                    "phase": "stage_started",
                    "stage": "referenced_images",
                    "total_bytes": 8192,
                }
            )
            progress(
                {
                    "phase": "stage_progress",
                    "stage": "referenced_images",
                    "bytes_written": 4096,
                    "total_bytes": 8192,
                    "bytes_per_second": 128,
                    "elapsed_seconds": 31,
                }
            )
            progress(
                {
                    "phase": "stage_verifying",
                    "stage": "referenced_images",
                    "bytes_written": 8192,
                    "total_bytes": 8192,
                }
            )
            progress(
                {
                    "phase": "stage_finished",
                    "stage": "referenced_images",
                    "status": "ok",
                    "bytes_written": 8192,
                    "total_bytes": 8192,
                    "elapsed_seconds": 32,
                }
            )

        text = output.getvalue()
        self.assertIn("import=verification status=running", text)
        self.assertIn("import=verification status=ok", text)
        self.assertIn(
            "import=referenced_images status=running bytes_total=8192",
            text,
        )
        self.assertIn("import=referenced_images status=running bytes=4096", text)
        self.assertIn("import=referenced_images status=verifying", text)
        self.assertIn("import=referenced_images status=ok bytes=8192", text)


if __name__ == "__main__":
    import unittest

    unittest.main()
