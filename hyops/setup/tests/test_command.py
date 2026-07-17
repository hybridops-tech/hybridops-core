from __future__ import annotations

import io
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import MagicMock, patch

from hyops.cli import main


REPO_ROOT = Path(__file__).resolve().parents[3]


def _write_galaxy_marker(runtime: str) -> None:
    collections = Path(runtime) / "state" / "ansible" / "galaxy_collections"
    collections.mkdir(parents=True)
    marker = collections.parent / ".installed.json"
    marker.write_text(
        f'{{"collections_dir": "{collections}"}}\n',
        encoding="utf-8",
    )


class SetupCommandTests(unittest.TestCase):
    def test_gcp_check_does_not_require_azure(self) -> None:
        with tempfile.TemporaryDirectory() as runtime, patch(
            "hyops.setup.command.shutil.which",
            side_effect=lambda command: None if command == "az" else f"/bin/{command}",
        ), patch(
            "hyops.setup.command.command_evidence_dir",
            return_value=Path(runtime) / "run-record",
        ):
            (Path(runtime) / "run-record").mkdir()
            _write_galaxy_marker(runtime)
            output = io.StringIO()
            with redirect_stdout(output):
                rc = main(
                    ["setup", "check", "gcp", "--runtime-root", runtime]
                )

        self.assertEqual(rc, 0)
        self.assertIn("ok      gcp-support", output.getvalue())
        self.assertNotIn("azure-support", output.getvalue())

    def test_gcp_check_requires_auth_plugin(self) -> None:
        with tempfile.TemporaryDirectory() as runtime, patch(
            "hyops.setup.command.shutil.which",
            side_effect=lambda command: (
                None if command == "gke-gcloud-auth-plugin" else f"/bin/{command}"
            ),
        ), patch(
            "hyops.setup.command.command_evidence_dir",
            return_value=Path(runtime) / "run-record",
        ):
            (Path(runtime) / "run-record").mkdir()
            _write_galaxy_marker(runtime)
            output = io.StringIO()
            with redirect_stdout(output):
                rc = main(
                    ["setup", "check", "gcp", "--runtime-root", runtime]
                )

        self.assertEqual(rc, 2)
        self.assertIn(
            "missing gcp-support: gke-gcloud-auth-plugin",
            output.getvalue(),
        )
        self.assertIn("status=not-ready", output.getvalue())

    def test_proxmox_check_requires_galaxy_marker(self) -> None:
        with tempfile.TemporaryDirectory() as runtime, patch(
            "hyops.setup.command.shutil.which", return_value="/bin/tool"
        ), patch(
            "hyops.setup.command.command_evidence_dir",
            return_value=Path(runtime) / "run-record",
        ):
            (Path(runtime) / "run-record").mkdir()
            output = io.StringIO()
            with redirect_stdout(output):
                rc = main(
                    ["setup", "check", "proxmox", "--runtime-root", runtime]
                )

        self.assertEqual(rc, 2)
        self.assertIn(
            "missing galaxy-dependencies: run: hyops setup galaxy",
            output.getvalue(),
        )

    def test_base_check_does_not_require_provider_or_galaxy(self) -> None:
        with tempfile.TemporaryDirectory() as runtime, patch(
            "hyops.setup.command.shutil.which", return_value="/bin/tool"
        ), patch(
            "hyops.setup.command.command_evidence_dir",
            return_value=Path(runtime) / "run-record",
        ):
            (Path(runtime) / "run-record").mkdir()
            output = io.StringIO()
            with redirect_stdout(output):
                rc = main(
                    ["setup", "check", "base", "--runtime-root", runtime]
                )

        self.assertEqual(rc, 0)
        self.assertNotIn("gcp-support", output.getvalue())
        self.assertNotIn("azure-support", output.getvalue())
        self.assertNotIn("galaxy-dependencies", output.getvalue())

    def test_target_progress_reaches_100_percent(self) -> None:
        display = MagicMock()
        display.enabled = True
        with tempfile.TemporaryDirectory() as runtime, patch(
            "hyops.setup.command.run_streamed", return_value=0
        ), patch(
            "hyops.setup.command.ProgressDisplay", return_value=display
        ), patch(
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
        self.assertIn("100%", display.finish.call_args_list[-1].args[1])

    def test_target_progress_stops_at_failed_stage(self) -> None:
        display = MagicMock()
        display.enabled = True
        with tempfile.TemporaryDirectory() as runtime, patch(
            "hyops.setup.command.run_streamed", side_effect=[0, 7]
        ), patch(
            "hyops.setup.command.ProgressDisplay", return_value=display
        ), patch(
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

        self.assertEqual(rc, 7)
        failed_label = display.finish.call_args_list[-1].args[1]
        self.assertIn("70%", failed_label)
        self.assertNotIn("100%", failed_label)

    def test_target_dry_run_lists_composed_steps(self) -> None:
        cases = {
            "gcp": ("base", "cloud-gcp", "galaxy"),
            "azure": ("base", "cloud-azure", "galaxy"),
            "proxmox": ("base", "galaxy"),
            "all": ("base", "cloud-azure", "cloud-gcp", "galaxy"),
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

    def test_individual_base_setup_elevates_automatically_on_linux(self) -> None:
        with tempfile.TemporaryDirectory() as runtime, patch(
            "hyops.setup.command.run_streamed", return_value=0
        ) as run_streamed, patch(
            "hyops.setup.command.command_evidence_dir",
            return_value=Path(runtime) / "run-record",
        ):
            rc = main(
                [
                    "setup",
                    "base",
                    "--root",
                    str(REPO_ROOT),
                    "--runtime-root",
                    runtime,
                ]
            )

        self.assertEqual(rc, 0)
        self.assertEqual(
            run_streamed.call_args.args[0][:3],
            ["sudo", "-H", "-E"],
        )

    def test_all_setup_elevates_system_stages_only(self) -> None:
        with tempfile.TemporaryDirectory() as runtime, patch(
            "hyops.setup.command.run_streamed", return_value=0
        ) as run_streamed, patch(
            "hyops.setup.command.command_evidence_dir",
            return_value=Path(runtime) / "run-record",
        ):
            rc = main(
                [
                    "setup",
                    "all",
                    "--root",
                    str(REPO_ROOT),
                    "--runtime-root",
                    runtime,
                ]
            )

        self.assertEqual(rc, 0)
        self.assertEqual(run_streamed.call_count, 4)
        for call in run_streamed.call_args_list[:3]:
            self.assertEqual(call.args[0][:3], ["sudo", "-H", "-E"])
        self.assertEqual(run_streamed.call_args_list[3].args[0][0], "bash")

    def test_individual_setup_uses_percentage_without_elapsed_time(self) -> None:
        display = MagicMock()
        display.enabled = True

        def run_with_progress(*args, **kwargs):
            callback = kwargs["line_callback"]
            callback("[hyops-progress] Preparing system packages")
            callback("[hyops-progress] Installing automation runtime")
            return 0

        with tempfile.TemporaryDirectory() as runtime, patch(
            "hyops.setup.command.run_streamed", side_effect=run_with_progress
        ), patch(
            "hyops.setup.command.ProgressDisplay", return_value=display
        ) as progress_class, patch(
            "hyops.setup.command.command_evidence_dir",
            return_value=Path(runtime) / "run-record",
        ):
            rc = main(
                [
                    "setup",
                    "base",
                    "--root",
                    str(REPO_ROOT),
                    "--runtime-root",
                    runtime,
                ]
            )

        self.assertEqual(rc, 0)
        progress_class.assert_called_once_with(show_elapsed=False)
        self.assertIn("21%", display.update.call_args_list[-1].args[1])
        self.assertIn("100%", display.finish.call_args.args[1])

    def test_individual_setup_reports_cancellation(self) -> None:
        display = MagicMock()
        display.enabled = True
        with tempfile.TemporaryDirectory() as runtime, patch(
            "hyops.setup.command.run_streamed", return_value=130
        ), patch(
            "hyops.setup.command.ProgressDisplay", return_value=display
        ), patch(
            "hyops.setup.command.command_evidence_dir",
            return_value=Path(runtime) / "run-record",
        ):
            rc = main(
                [
                    "setup",
                    "base",
                    "--root",
                    str(REPO_ROOT),
                    "--runtime-root",
                    runtime,
                ]
            )

        self.assertEqual(rc, 130)
        self.assertEqual(display.finish.call_args.args[2], "cancelled")


if __name__ == "__main__":
    unittest.main()
