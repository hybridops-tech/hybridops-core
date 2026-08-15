"""Runtime directory layout verification."""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

from hyops.runtime.layout import _ensure_dir, ensure_layout
from hyops.runtime.paths import resolve_runtime_paths


class RuntimeLayoutTests(unittest.TestCase):
    def test_ensure_dir_tightens_loose_directory(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            target = root / "loose_dir"

            # Create a directory with loose permissions (0o777)
            target.mkdir()
            os.chmod(target, 0o777)

            # Run ensure_dir
            created = _ensure_dir(target, 0o700)
            self.assertFalse(created)

            if os.name == "posix":
                mode = os.stat(target).st_mode & 0o777
                self.assertEqual(mode, 0o700)

    def test_ensure_dir_creates_with_correct_permissions(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            target = root / "new_dir"

            created = _ensure_dir(target, 0o700)
            self.assertTrue(created)
            self.assertTrue(target.is_dir())

            if os.name == "posix":
                mode = os.stat(target).st_mode & 0o777
                self.assertEqual(mode, 0o700)

    def test_ensure_dir_idempotent_second_run(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            target = root / "idempotent_dir"

            created_first = _ensure_dir(target, 0o700)
            self.assertTrue(created_first)

            # Second run
            created_second = _ensure_dir(target, 0o700)
            self.assertFalse(created_second)

            if os.name == "posix":
                mode = os.stat(target).st_mode & 0o777
                self.assertEqual(mode, 0o700)

    def test_ensure_dir_raises_error_if_existing_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            target = root / "existing_file"

            # Create a file instead of a directory
            target.write_text("file content")

            with self.assertRaises(RuntimeError) as ctx:
                _ensure_dir(target, 0o700)

            msg = "Path exists but is not a directory"
            self.assertIn(msg, str(ctx.exception))

    def test_ensure_layout_tightens_loose_root_and_child(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / ".hybridops"

            # Loose root
            root.mkdir()
            os.chmod(root, 0o777)

            # Loose child
            child = root / "state"
            child.mkdir()
            os.chmod(child, 0o777)

            paths = resolve_runtime_paths(str(root))
            result = ensure_layout(paths)

            # Root and child were not created, but tightened
            self.assertNotIn(root, result.created)
            self.assertIn(root, result.ensured)
            self.assertNotIn(child, result.created)
            self.assertIn(child, result.ensured)

            if os.name == "posix":
                self.assertEqual(os.stat(root).st_mode & 0o777, 0o700)
                self.assertEqual(os.stat(child).st_mode & 0o777, 0o700)


if __name__ == "__main__":
    unittest.main()
