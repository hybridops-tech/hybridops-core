"""Tests for blueprint preflight bypass governance."""

from __future__ import annotations

import argparse
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import patch

from hyops.blueprint.command import run_deploy
from hyops.runtime.exitcodes import OPERATOR_ERROR
from hyops.runtime.paths import RuntimePaths
from hyops.runner.command import _remote_blueprint_command


def _payload() -> dict:
    return {
        "blueprint_ref": "test/lab@v1",
        "mode": "hybrid",
        "path": "/tmp/blueprint.yml",
        "order": ["host"],
        "steps": [
            {
                "id": "host",
                "module_ref": "platform/test/host",
                "state_instance": "host",
                "action": "deploy",
                "phase": "platform",
                "optional": False,
                "with_deps": False,
            }
        ],
        "policy": {"fail_fast": True},
    }


def _namespace(
    root: Path,
    *,
    skip_preflight: bool = True,
    reason: str | None,
) -> argparse.Namespace:
    return argparse.Namespace(
        execute=True,
        json=False,
        yes=True,
        root=str(root),
        env=None,
        ref="test/lab@v1",
        file="",
        blueprints_root="blueprints",
        module_root="modules",
        out_dir=None,
        deps_inputs_dir=None,
        deps_force=False,
        skip_preflight=skip_preflight,
        preflight_bypass_reason=reason,
        restore_labs=False,
        skip_lab_restore=False,
        overwrite_labs=False,
    )


class BlueprintPreflightBypassTest(TestCase):
    def test_mutating_blueprint_bypass_requires_reason(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            paths = RuntimePaths.from_root(root)
            with (
                patch("hyops.blueprint.command._resolve_and_validate", return_value=_payload()),
                patch("hyops.blueprint.command.require_runtime_selection"),
                patch("hyops.blueprint.command.resolve_runtime_paths", return_value=paths),
                patch("hyops.blueprint.command.ensure_layout"),
                patch("hyops.blueprint.command.require_runtime_writable"),
                patch("hyops.blueprint.command._enforce_runtime_blueprint_file_scope"),
                patch("hyops.blueprint.command.run_step_module_command") as step_command,
            ):
                rc = run_deploy(_namespace(root, reason=None))

        self.assertEqual(rc, OPERATOR_ERROR)
        step_command.assert_not_called()

    def test_bypass_decision_is_propagated_to_executed_steps(self) -> None:
        captured: dict = {}

        def run_step(_step, _payload, ns, _paths):
            captured.update(ns.preflight_context)
            return 0

        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            paths = RuntimePaths.from_root(root)
            with (
                patch("hyops.blueprint.command._resolve_and_validate", return_value=_payload()),
                patch("hyops.blueprint.command.require_runtime_selection"),
                patch("hyops.blueprint.command.resolve_runtime_paths", return_value=paths),
                patch("hyops.blueprint.command.ensure_layout"),
                patch("hyops.blueprint.command.require_runtime_writable"),
                patch("hyops.blueprint.command._enforce_runtime_blueprint_file_scope"),
                patch("hyops.blueprint.command._confirm_deploy_if_needed", return_value=0),
                patch("hyops.blueprint.command.resolved_step_inputs_file", return_value=None),
                patch("hyops.blueprint.command.module_state_ok", return_value=False),
                patch("hyops.blueprint.command.enforce_step_contracts"),
                patch("hyops.blueprint.command.run_step_module_command", side_effect=run_step),
            ):
                rc = run_deploy(
                    _namespace(root, reason="controlled provider recovery")
                )

        self.assertEqual(rc, 0)
        self.assertEqual(captured["scope"], "blueprint")
        self.assertEqual(captured["decision"], "bypass")
        self.assertEqual(captured["status"], "bypassed")
        self.assertEqual(captured["reason"], "controlled provider recovery")

    def test_checked_decision_is_propagated_to_executed_steps(self) -> None:
        captured: dict = {}

        def run_step(_step, _payload, ns, _paths):
            captured.update(ns.preflight_context)
            return 0

        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            paths = RuntimePaths.from_root(root)
            preflight_steps = [{"id": "host", "status": "ready"}]
            with (
                patch("hyops.blueprint.command._resolve_and_validate", return_value=_payload()),
                patch("hyops.blueprint.command.require_runtime_selection"),
                patch("hyops.blueprint.command.resolve_runtime_paths", return_value=paths),
                patch("hyops.blueprint.command.ensure_layout"),
                patch("hyops.blueprint.command.require_runtime_writable"),
                patch("hyops.blueprint.command._enforce_runtime_blueprint_file_scope"),
                patch(
                    "hyops.blueprint.command.compute_preflight",
                    return_value=(preflight_steps, [], []),
                ),
                patch("hyops.blueprint.command._confirm_deploy_if_needed", return_value=0),
                patch("hyops.blueprint.command.resolved_step_inputs_file", return_value=None),
                patch("hyops.blueprint.command.module_state_ok", return_value=False),
                patch("hyops.blueprint.command.enforce_step_contracts"),
                patch("hyops.blueprint.command.run_step_module_command", side_effect=run_step),
            ):
                rc = run_deploy(
                    _namespace(
                        root,
                        skip_preflight=False,
                        reason=None,
                    )
                )

        self.assertEqual(rc, 0)
        self.assertEqual(captured["scope"], "blueprint")
        self.assertEqual(captured["decision"], "enforce")
        self.assertEqual(captured["status"], "passed")
        self.assertEqual(captured["guarantee"], "established")

    def test_failed_deploy_offers_cleanup(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            paths = RuntimePaths.from_root(root)
            with (
                patch("hyops.blueprint.command._resolve_and_validate", return_value=_payload()),
                patch("hyops.blueprint.command.require_runtime_selection"),
                patch("hyops.blueprint.command.resolve_runtime_paths", return_value=paths),
                patch("hyops.blueprint.command.ensure_layout"),
                patch("hyops.blueprint.command.require_runtime_writable"),
                patch("hyops.blueprint.command._enforce_runtime_blueprint_file_scope"),
                patch("hyops.blueprint.command._confirm_deploy_if_needed", return_value=0),
                patch("hyops.blueprint.command.resolved_step_inputs_file", return_value=None),
                patch("hyops.blueprint.command.module_state_ok", return_value=False),
                patch("hyops.blueprint.command.enforce_step_contracts"),
                patch("hyops.blueprint.command.run_step_module_command", return_value=2),
                patch("hyops.blueprint.command._failed_deploy_has_resources", return_value=True),
                patch("hyops.blueprint.command._offer_failed_deploy_destroy") as cleanup,
            ):
                rc = run_deploy(
                    _namespace(root, reason="controlled provider recovery")
                )

        self.assertEqual(rc, OPERATOR_ERROR)
        cleanup.assert_called_once()

    def test_runner_forwards_bypass_reason_to_remote_command(self) -> None:
        ns = SimpleNamespace(
            runner_blueprint_cmd="deploy",
            execute=True,
            skip_preflight=True,
            preflight_bypass_reason="controlled provider recovery",
            yes=True,
        )
        ctx = SimpleNamespace(remote_hyops="/opt/hybridops/bin/hyops")

        command = _remote_blueprint_command(
            ns,
            runtime_root="/tmp/runtime",
            remote_blueprint_path="/tmp/runtime/config/blueprints/lab.yml",
            ctx=ctx,
        )

        self.assertIn("--skip-preflight", command)
        reason_index = command.index("--preflight-bypass-reason")
        self.assertEqual(command[reason_index + 1], "controlled provider recovery")


if __name__ == "__main__":
    import unittest

    unittest.main()
