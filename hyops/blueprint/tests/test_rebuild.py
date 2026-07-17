"""Tests for the explicit blueprint rebuild lifecycle."""

from __future__ import annotations

import argparse
import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from hyops.blueprint.command import run_rebuild


def _payload() -> dict:
    return {
        "blueprint_ref": "gcp/eve-ng@v1",
        "mode": "hybrid",
        "path": "/tmp/blueprint.yml",
        "order": ["network", "vm", "config"],
        "steps": [
            {"id": "network", "retain_on_destroy": True},
            {"id": "vm"},
            {"id": "config"},
        ],
        "policy": {},
    }


def _namespace(root: str, *, execute: bool) -> argparse.Namespace:
    return argparse.Namespace(
        root=root,
        env=None,
        execute=execute,
        yes=True,
        json=False,
        ref="gcp/eve-ng@v1",
        file="",
        blueprints_root="blueprints",
        module_root="modules",
        out_dir=None,
        deps_inputs_dir=None,
        deps_force=False,
        skip_preflight=False,
    )


class BlueprintRebuildTests(unittest.TestCase):
    def test_plan_marks_retained_destroy_steps(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, patch(
            "hyops.blueprint.command._resolve_and_validate", return_value=_payload()
        ), patch("builtins.print") as output:
            self.assertEqual(run_rebuild(_namespace(tmp, execute=False)), 0)
            output.assert_any_call("  - Network (retained)")

    def test_plan_only_does_not_execute(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, patch(
            "hyops.blueprint.command._resolve_and_validate", return_value=_payload()
        ), patch("hyops.blueprint.command.run_destroy") as destroy, patch(
            "hyops.blueprint.command.run_deploy"
        ) as deploy:
            self.assertEqual(run_rebuild(_namespace(tmp, execute=False)), 0)
            destroy.assert_not_called()
            deploy.assert_not_called()

    def test_failed_destroy_prevents_deploy(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, patch(
            "hyops.blueprint.command._resolve_and_validate", return_value=_payload()
        ), patch(
            "hyops.blueprint.command.new_run_id", return_value="rebuild-test"
        ), patch("hyops.blueprint.command.run_destroy", return_value=2), patch(
            "hyops.blueprint.command.run_deploy"
        ) as deploy:
            self.assertEqual(run_rebuild(_namespace(tmp, execute=True)), 2)
            deploy.assert_not_called()
            records = list(
                Path(tmp).glob("logs/blueprint/gcp_eve-ng_v1/*/rebuild.json")
            )
            self.assertEqual(len(records), 1)
            self.assertIn('"status": "destroy-failed"', records[0].read_text())

    def test_successful_destroy_runs_deploy(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, patch(
            "hyops.blueprint.command._resolve_and_validate", return_value=_payload()
        ), patch(
            "hyops.blueprint.command.new_run_id", return_value="rebuild-test"
        ), patch("hyops.blueprint.command.run_destroy", return_value=0), patch(
            "hyops.blueprint.command.run_deploy", return_value=0
        ) as deploy:
            self.assertEqual(run_rebuild(_namespace(tmp, execute=True)), 0)
            deploy.assert_called_once()

    def test_execute_omits_order_lists_in_default_output(self) -> None:
        output = io.StringIO()
        with tempfile.TemporaryDirectory() as tmp, patch(
            "hyops.blueprint.command._resolve_and_validate", return_value=_payload()
        ), patch(
            "hyops.blueprint.command.new_run_id", return_value="rebuild-test"
        ), patch("hyops.blueprint.command.run_destroy", return_value=0), patch(
            "hyops.blueprint.command.run_deploy", return_value=0
        ), patch("sys.stdout", output):
            self.assertEqual(run_rebuild(_namespace(tmp, execute=True)), 0)

        rendered = output.getvalue()
        self.assertNotIn("destroy_order:", rendered)
        self.assertNotIn("deploy_order:", rendered)


if __name__ == "__main__":
    unittest.main()
