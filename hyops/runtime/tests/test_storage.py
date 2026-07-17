"""Runtime storage failure detection and guidance."""

from __future__ import annotations

import errno
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from hyops.runtime.storage import check_runtime_writable, format_runtime_storage_error


class RuntimeStorageTests(unittest.TestCase):
    def test_writable_runtime_probe_is_removed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            writable, detail = check_runtime_writable(root)

            self.assertTrue(writable)
            self.assertEqual(detail, str(root))
            self.assertEqual(list(root.iterdir()), [])

    @patch("hyops.runtime.storage.is_wsl", return_value=True)
    def test_read_only_wsl_error_has_recovery_command(self, _is_wsl) -> None:
        detail = format_runtime_storage_error(
            OSError(errno.EROFS, "Read-only file system")
        )

        self.assertIn("wsl --shutdown", detail)
        self.assertIn("Microsoft WSL disk-repair procedure", detail)


if __name__ == "__main__":
    unittest.main()
