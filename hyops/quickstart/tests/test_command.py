"""Public CLI tests for the credential-free first-run workflow."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import unittest
from argparse import Namespace
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from hyops.quickstart import command as quickstart_command


REPO_ROOT = Path(__file__).resolve().parents[3]


def run_cli(root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["PYTHONPATH"] = str(REPO_ROOT)
    return subprocess.run(
        [sys.executable, "-m", "hyops.cli", "quickstart", *args, "--root", str(root)],
        cwd=REPO_ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )


class QuickstartCommandTests(unittest.TestCase):
    def test_cli_import_does_not_resolve_home(self) -> None:
        script = """
from pathlib import Path

def unavailable_home(cls):
    raise RuntimeError("home unavailable")

Path.home = classmethod(unavailable_home)
import hyops.cli
"""
        result = subprocess.run(
            [sys.executable, "-c", script],
            cwd=REPO_ROOT,
            env={**os.environ, "PYTHONPATH": str(REPO_ROOT)},
            text=True,
            capture_output=True,
            check=False,
        )

        self.assertEqual(result.returncode, 0, result.stderr)

    def test_explicit_root_does_not_require_home(self) -> None:
        with TemporaryDirectory() as tmp:
            stdout = StringIO()
            ns = Namespace(action="status", root=tmp, json=True)
            with patch.object(
                Path,
                "home",
                side_effect=RuntimeError("home unavailable"),
            ), redirect_stdout(stdout):
                rc = quickstart_command.run(ns)

            self.assertEqual(rc, 0)
            self.assertEqual(json.loads(stdout.getvalue())["status"], "not_started")

    def test_missing_home_for_default_root_is_reported_without_traceback(self) -> None:
        stderr = StringIO()
        ns = Namespace(action="status", root=None, json=False)
        with patch.object(
            Path,
            "home",
            side_effect=RuntimeError("home unavailable"),
        ), redirect_stderr(stderr):
            rc = quickstart_command.run(ns)

        self.assertEqual(rc, 2)
        self.assertIn("home unavailable", stderr.getvalue())
        self.assertNotIn("Traceback", stderr.getvalue())

    def test_run_status_repeat_and_reset(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp) / "quickstart"

            before = run_cli(root, "status", "--json")
            first = run_cli(root)
            status = run_cli(root, "status", "--json")
            repeat = run_cli(root)
            reset = run_cli(root, "reset")
            after = run_cli(root, "status", "--json")

            self.assertEqual(before.returncode, 0, before.stderr)
            self.assertEqual(json.loads(before.stdout)["status"], "not_started")
            self.assertEqual(first.returncode, 0, first.stderr)
            self.assertIn("Quickstart complete.", first.stdout)
            self.assertEqual(status.returncode, 0, status.stderr)
            self.assertEqual(json.loads(status.stdout)["status"], "ready")
            self.assertEqual(repeat.returncode, 0, repeat.stderr)
            self.assertEqual(reset.returncode, 0, reset.stderr)
            self.assertEqual(json.loads(after.stdout)["status"], "reset")

            artifact = root / "state" / "managed" / "local-artifact" / "quickstart.json"
            self.assertFalse(artifact.exists())

    def test_drift_blocks_run_until_reset(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp) / "quickstart"
            first = run_cli(root)
            self.assertEqual(first.returncode, 0, first.stderr)
            artifact = (
                root / "state" / "managed" / "local-artifact" / "quickstart.json"
            )
            artifact.write_text(json.dumps({"changed": True}), encoding="utf-8")

            blocked = run_cli(root)
            artifact.write_text("not-json", encoding="utf-8")
            reset = run_cli(root, "reset")
            recovered = run_cli(root)

            self.assertEqual(blocked.returncode, 1)
            self.assertIn("differs from declared intent", blocked.stderr)
            self.assertIn("run record:", blocked.stderr)
            self.assertEqual(reset.returncode, 0, reset.stderr)
            self.assertEqual(recovered.returncode, 0, recovered.stderr)

    def test_initialized_runtime_root_is_rejected_without_changes(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp) / "existing-environment"
            blueprint = root / "config" / "blueprints" / "environment.yml"
            blueprint.parent.mkdir(parents=True)
            blueprint.write_text("blueprint_ref: test/environment@v1\n", encoding="utf-8")

            result = run_cli(root)

            self.assertEqual(result.returncode, 2)
            self.assertIn("initialized blueprints", result.stderr)
            self.assertEqual(
                blueprint.read_text(encoding="utf-8"),
                "blueprint_ref: test/environment@v1\n",
            )
            self.assertFalse((root / "work").exists())

    def test_pruning_work_does_not_remove_managed_outcome(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp) / "quickstart"
            first = run_cli(root)
            self.assertEqual(first.returncode, 0, first.stderr)

            shutil.rmtree(root / "work")
            status = run_cli(root, "status", "--json")

            self.assertEqual(status.returncode, 0, status.stderr)
            self.assertEqual(json.loads(status.stdout)["status"], "ready")

    def test_nested_runtime_symlink_is_rejected_without_touching_target(self) -> None:
        with TemporaryDirectory() as tmp:
            base = Path(tmp)
            root = base / "quickstart"
            outside = base / "outside-state"
            root.mkdir()
            outside.mkdir(mode=0o755)
            (root / "state").symlink_to(outside, target_is_directory=True)

            result = run_cli(root)

            self.assertEqual(result.returncode, 2)
            self.assertIn("symbolic links", result.stderr)
            self.assertEqual(outside.stat().st_mode & 0o777, 0o755)
            self.assertEqual(list(outside.iterdir()), [])

    def test_layout_failure_is_reported_without_traceback(self) -> None:
        with TemporaryDirectory() as tmp:
            stderr = StringIO()
            ns = Namespace(action="run", root=tmp, json=False)
            with patch.object(
                quickstart_command,
                "ensure_layout",
                side_effect=PermissionError("permission denied"),
            ), redirect_stderr(stderr):
                rc = quickstart_command.run(ns)

            self.assertEqual(rc, 1)
            self.assertIn("failed to prepare quickstart runtime", stderr.getvalue())
            self.assertNotIn("Traceback", stderr.getvalue())


if __name__ == "__main__":
    unittest.main()
