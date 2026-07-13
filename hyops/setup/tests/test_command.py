from __future__ import annotations

import io
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from hyops.cli import main


REPO_ROOT = Path(__file__).resolve().parents[3]


class SetupCommandTests(unittest.TestCase):
    def test_target_dry_run_lists_composed_steps(self) -> None:
        cases = {
            "gcp": ("base", "cloud-gcp", "galaxy"),
            "azure": ("base", "cloud-azure", "galaxy"),
            "proxmox": ("base", "galaxy"),
        }
        for target, expected in cases.items():
            with self.subTest(target=target), tempfile.TemporaryDirectory() as runtime:
                output = io.StringIO()
                with redirect_stdout(output):
                    rc = main(
                        [
                            "setup",
                            target,
                            "--root",
                            str(REPO_ROOT),
                            "--runtime-root",
                            runtime,
                            "--dry-run",
                        ]
                    )
                self.assertEqual(rc, 0)
                for step in expected:
                    self.assertIn(f"- {step}:", output.getvalue())

    def test_target_runs_privileged_steps_without_privileging_galaxy(self) -> None:
        with tempfile.TemporaryDirectory() as runtime, patch(
            "hyops.setup.command.run_streamed", return_value=0
        ) as run_streamed, patch(
            "hyops.setup.command.command_evidence_dir",
            return_value=Path(runtime) / "run-record",
        ):
            rc = main(
                [
                    "setup",
                    "proxmox",
                    "--root",
                    str(REPO_ROOT),
                    "--runtime-root",
                    runtime,
                ]
            )

        self.assertEqual(rc, 0)
        self.assertEqual(run_streamed.call_count, 2)
        base_argv = run_streamed.call_args_list[0].args[0]
        galaxy_argv = run_streamed.call_args_list[1].args[0]
        self.assertEqual(base_argv[:3], ["sudo", "-H", "-E"])
        self.assertEqual(galaxy_argv[0], "bash")
        self.assertIn("--root", galaxy_argv)

    def test_verbose_is_accepted_after_setup_action(self) -> None:
        with tempfile.TemporaryDirectory() as runtime:
            rc = main(
                [
                    "setup",
                    "gcp",
                    "--root",
                    str(REPO_ROOT),
                    "--runtime-root",
                    runtime,
                    "--verbose",
                    "--dry-run",
                ]
            )
        self.assertEqual(rc, 0)


if __name__ == "__main__":
    unittest.main()
