from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import patch

from hyops.blueprint.command import run_destroy


def _payload():
    steps = []
    for step_id in ("network", "vm", "health"):
        steps.append(
            {
                "id": step_id,
                "module_ref": f"platform/test/{step_id}",
                "state_instance": step_id,
                "action": "deploy",
                "phase": "operations",
                "optional": False,
            }
        )
    return {
        "blueprint_ref": "test/resumable@v1",
        "mode": "hybrid",
        "path": "/tmp/blueprint.yml",
        "order": ["network", "vm", "health"],
        "steps": steps,
        "policy": {"fail_fast": True},
    }


def _namespace():
    return SimpleNamespace(
        execute=True,
        yes=True,
        json=False,
        root=None,
        env="test",
        file=None,
    )


class ResumableBlueprintDestroyTest(TestCase):
    def _run(self, statuses, run_step):
        paths = SimpleNamespace(state_dir="/tmp/state", root=SimpleNamespace(name="test"))

        def state_status(_state_dir, state_ref):
            return statuses[state_ref.rsplit("#", 1)[-1]]

        with (
            patch("hyops.blueprint.command._resolve_and_validate", return_value=_payload()),
            patch("hyops.blueprint.command.require_runtime_selection"),
            patch("hyops.blueprint.command.resolve_runtime_paths", return_value=paths),
            patch("hyops.blueprint.command.ensure_layout"),
            patch("hyops.blueprint.command._enforce_runtime_blueprint_file_scope"),
            patch("hyops.blueprint.command.module_state_status", side_effect=state_status),
            patch("hyops.blueprint.command.resolved_step_inputs_file", return_value=None) as inputs_file,
            patch("hyops.blueprint.command.run_step_module_command", side_effect=run_step) as command,
        ):
            rc = run_destroy(_namespace())
        return rc, inputs_file, command

    def test_second_destroy_skips_terminal_state_before_inputs(self):
        rc, inputs_file, command = self._run(
            {"network": "destroyed", "vm": "absent", "health": "destroyed"},
            [],
        )

        self.assertEqual(rc, 0)
        inputs_file.assert_not_called()
        command.assert_not_called()

    def test_partial_destroy_runs_only_remaining_live_step(self):
        rc, inputs_file, command = self._run(
            {"network": "destroyed", "vm": "ok", "health": "destroyed"},
            [0],
        )

        self.assertEqual(rc, 0)
        self.assertEqual(inputs_file.call_count, 1)
        self.assertEqual(command.call_count, 1)
        self.assertEqual(command.call_args.args[0]["id"], "vm")

    def test_live_step_failure_remains_fatal(self):
        rc, inputs_file, command = self._run(
            {"network": "ok", "vm": "destroyed", "health": "destroyed"},
            [2],
        )

        self.assertEqual(rc, 2)
        self.assertEqual(inputs_file.call_count, 1)
        self.assertEqual(command.call_count, 1)
