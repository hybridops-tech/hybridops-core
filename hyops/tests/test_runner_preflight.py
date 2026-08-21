"""Tests for runner preflight decision propagation."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import patch

from hyops.runner.command import (
    _execute_runner_blueprint,
    _remote_blueprint_command,
)
from hyops.runtime.exitcodes import OPERATOR_ERROR
from hyops.runtime.paths import RuntimePaths


def _namespace(root: Path, *, reason: str | None) -> argparse.Namespace:
    return argparse.Namespace(
        root=str(root),
        env=None,
        file=str(root / "config/blueprints/lab.yml"),
        runner_blueprint_cmd="deploy",
        runner_state_ref="platform/linux/ops-runner#test",
        runner_vm_key="runner",
        execute=True,
        skip_preflight=True,
        preflight_bypass_reason=reason,
        yes=True,
        sync_env=[],
        secret_source="runtime",
        keep_remote_job=False,
    )


class RunnerPreflightDecisionTest(TestCase):
    def test_missing_reason_stops_before_dispatch(self) -> None:
        with patch("hyops.runner.command._sync_runtime_to_runner") as dispatch:
            rc = _execute_runner_blueprint(_namespace(Path("/tmp/runtime"), reason=None))

        self.assertEqual(rc, OPERATOR_ERROR)
        dispatch.assert_not_called()

    def test_bypass_decision_is_recorded_before_remote_execution(self) -> None:
        temporary = TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        paths = RuntimePaths.from_root(root)
        blueprint_path = root / "config/blueprints/lab.yml"
        context = SimpleNamespace(
            state_ref="platform/linux/ops-runner#test",
            vm_key="runner",
            remote_hyops="/opt/hybridops/bin/hyops",
            remote_core_root="/opt/hybridops/core",
        )
        observed: dict[str, object] = {}

        def sync_runtime(*_args, **_kwargs):
            record_path = root / "logs/runner/runner-test/dispatch.request.json"
            observed["request"] = json.loads(record_path.read_text(encoding="utf-8"))
            return "/tmp/job", "/tmp/job/runtime", "/tmp/job/dispatch.env"

        def build_remote_command(ns, **kwargs):
            command = _remote_blueprint_command(ns, **kwargs)
            observed["command"] = command
            return command

        with (
            patch("hyops.runner.command.require_runtime_selection"),
            patch("hyops.runner.command.resolve_runtime_paths", return_value=paths),
            patch("hyops.runner.command.ensure_layout"),
            patch(
                "hyops.runner.command._enforce_runtime_blueprint_file_scope",
                return_value=blueprint_path,
            ),
            patch("hyops.runner.command._sync_secret_source_to_runtime"),
            patch("hyops.runner.command._resolve_runner_context", return_value=context),
            patch(
                "hyops.runner.command._resolve_sync_env_values",
                return_value=({}, [], ""),
            ),
            patch(
                "hyops.runner.command._resolve_tfc_dispatch_env",
                return_value=({}, {"enabled": "false"}),
            ),
            patch(
                "hyops.runner.command._resolve_gcp_dispatch_env",
                return_value=({}, {"enabled": "false"}),
            ),
            patch("hyops.runner.command.new_run_id", return_value="runner-test"),
            patch(
                "hyops.runner.command._sync_runtime_to_runner",
                side_effect=sync_runtime,
            ),
            patch(
                "hyops.runner.command._remote_blueprint_command",
                side_effect=build_remote_command,
            ),
            patch("hyops.runner.command._ssh_argv", return_value=["ssh", "runner"]),
            patch(
                "hyops.runner.command.run_capture_stream",
                return_value=SimpleNamespace(rc=0, stdout=""),
            ),
            patch("hyops.runner.command._sync_runtime_back"),
            patch("hyops.runner.command._cleanup_local_stage"),
            patch("hyops.runner.command._cleanup_remote_job"),
        ):
            rc = _execute_runner_blueprint(
                _namespace(root, reason="controlled provider recovery")
            )

        self.assertEqual(rc, 0)
        request = observed["request"]
        self.assertIsInstance(request, dict)
        decision = request["preflight"]
        self.assertEqual(decision["schema_version"], 1)
        self.assertEqual(decision["scope"], "blueprint")
        self.assertEqual(decision["decision"], "bypass")
        self.assertEqual(decision["status"], "bypassed")
        self.assertEqual(decision["guarantee"], "not-established")
        self.assertEqual(decision["decision_source"], "runner-cli")
        self.assertEqual(decision["reason"], "controlled provider recovery")

        command = observed["command"]
        self.assertIn("--skip-preflight", command)
        reason_index = command.index("--preflight-bypass-reason")
        self.assertEqual(command[reason_index + 1], "controlled provider recovery")


if __name__ == "__main__":
    import unittest

    unittest.main()
