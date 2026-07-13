"""Smoke tests for the public HybridOps command table."""

from __future__ import annotations

import os
import subprocess
import sys
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]


def run_cli(*args: str) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["PYTHONPATH"] = str(REPO_ROOT)
    return subprocess.run(
        [sys.executable, "-m", "hyops.cli", *args],
        cwd=REPO_ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )


class CliRoutingTests(unittest.TestCase):
    def test_version(self) -> None:
        result = run_cli("--version")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertRegex(result.stdout.strip(), r"^\d+\.\d+\.\d+(?:[-+].*)?$")

    def test_top_level_help_lists_public_commands(self) -> None:
        result = run_cli("--help")
        self.assertEqual(result.returncode, 0, result.stderr)
        for command in ("apply", "blueprint", "module", "state"):
            self.assertIn(command, result.stdout)

    def test_no_command_prints_help_and_returns_usage_error(self) -> None:
        result = run_cli()
        self.assertEqual(result.returncode, 2)
        self.assertIn("usage: hyops", result.stdout)

    def test_selected_command_help(self) -> None:
        for command in ("apply", "blueprint", "module", "state"):
            with self.subTest(command=command):
                result = run_cli(command, "--help")
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn(f"hyops {command}", result.stdout)

    def test_unknown_command_returns_parser_error(self) -> None:
        result = run_cli("not-a-command")
        self.assertEqual(result.returncode, 2)
        self.assertIn("invalid choice", result.stderr)


if __name__ == "__main__":
    unittest.main()
