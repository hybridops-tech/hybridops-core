"""Smoke tests for the public HybridOps command table."""

from __future__ import annotations

import os
import subprocess
import sys
import tomllib
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


PUBLIC_COMMANDS = (
    "apply",
    "blueprint",
    "deploy",
    "destroy",
    "import",
    "init",
    "inventory",
    "module",
    "plan",
    "preflight",
    "rebuild",
    "runner",
    "secrets",
    "setup",
    "show",
    "state",
    "test",
    "update",
    "validate",
    "vault",
)


class CliRoutingTests(unittest.TestCase):
    def test_version(self) -> None:
        result = run_cli("--version")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertRegex(result.stdout.strip(), r"^\d+\.\d+\.\d+(?:[-+].*)?$")

    def test_source_version_metadata_matches_runtime(self) -> None:
        import hyops

        project = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
        package_version = project["project"]["version"]

        self.assertEqual(package_version, hyops.__version__)
        self.assertFalse(package_version.startswith("0.0.0"))
        self.assertNotIn("dev", package_version.lower())

    def test_top_level_help_lists_public_commands(self) -> None:
        result = run_cli("--help")
        self.assertEqual(result.returncode, 0, result.stderr)
        for command in PUBLIC_COMMANDS:
            with self.subTest(command=command):
                self.assertIn(command, result.stdout)

    def test_top_level_help_omits_backend_maintenance_commands(self) -> None:
        result = run_cli("--help")
        self.assertEqual(result.returncode, 0, result.stderr)
        for command in ("terragrunt", "tfc", "stacks"):
            self.assertNotIn(command, result.stdout)

    def test_backend_maintenance_command_help_remains_available(self) -> None:
        for command in ("terragrunt", "tfc", "stacks"):
            with self.subTest(command=command):
                result = run_cli(command, "--help")
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn(f"hyops {command}", result.stdout)

    def test_no_command_prints_help_and_returns_usage_error(self) -> None:
        result = run_cli()
        self.assertEqual(result.returncode, 2)
        self.assertIn("usage: hyops", result.stdout)

    def test_selected_command_help(self) -> None:
        for command in PUBLIC_COMMANDS:
            with self.subTest(command=command):
                result = run_cli(command, "--help")
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn(f"hyops {command}", result.stdout)

    def test_blueprint_help_includes_edit(self) -> None:
        result = run_cli("blueprint", "--help")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("edit", result.stdout)

    def test_mutating_preflight_bypass_help_requires_reason(self) -> None:
        for args in (
            ("apply", "--help"),
            ("rebuild", "--help"),
            ("blueprint", "deploy", "--help"),
            ("blueprint", "rebuild", "--help"),
            ("runner", "blueprint", "deploy", "--help"),
        ):
            with self.subTest(args=args):
                result = run_cli(*args)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn("--preflight-bypass-reason", result.stdout)

    def test_unknown_command_returns_parser_error(self) -> None:
        result = run_cli("not-a-command")
        self.assertEqual(result.returncode, 2)
        self.assertIn("invalid choice", result.stderr)

    def test_secrets_exec_keeps_top_level_command_name(self) -> None:
        from hyops.cli import build_parser

        parsed = build_parser().parse_args(
            ["secrets", "exec", "--env", "test", "--", "true"]
        )

        self.assertEqual(parsed.cmd, "secrets")
        self.assertEqual(parsed.exec_argv, ["--", "true"])


if __name__ == "__main__":
    unittest.main()
