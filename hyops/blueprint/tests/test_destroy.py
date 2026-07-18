import io
import hashlib
import os
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import patch

from hyops.blueprint.command import (
    _destroyed_blueprint_cost_cleared,
    _gcp_blueprint_cost_estimate,
    _run_archive_before_destroy,
    _select_archive_destroy_mode,
    run_destroy,
)
from hyops.runtime.cost import CostEstimate


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
        archive_before_destroy=False,
        skip_archive=False,
    )


class ResumableBlueprintDestroyTest(TestCase):
    def test_standalone_destroy_resolves_cost_from_access_state(self):
        payload = {
            "blueprint_ref": "gcp/eve-ng@v1",
            "access": {
                "state_ref": "platform/gcp/platform-vm#gcp_eve_ng_vm",
            },
        }
        paths = SimpleNamespace(state_dir="/tmp/state", meta_dir=Path("/tmp/meta"))
        state = {
            "outputs": {
                "vms": {
                    "eve-ng-01": {
                        "vm_id": (
                            "projects/student-project/zones/europe-west2-b/"
                            "instances/eve-ng-01"
                        )
                    }
                }
            }
        }
        expected = CostEstimate(True)

        with (
            patch("hyops.blueprint.command.read_module_state", return_value=state),
            patch(
                "hyops.blueprint.command._gcp_cost_estimate_with_progress",
                return_value=expected,
            ) as estimate,
        ):
            result = _gcp_blueprint_cost_estimate(payload, paths)

        self.assertIs(result, expected)
        estimate.assert_called_once_with(
            project_id="student-project",
            zone="europe-west2-b",
            state=state,
            paths=paths,
        )

    def test_cost_is_cleared_only_when_every_step_is_terminal(self):
        payload = _payload()
        paths = SimpleNamespace(state_dir="/tmp/state")

        with patch(
            "hyops.blueprint.command.module_state_status",
            side_effect=("destroyed", "absent", "destroyed"),
        ):
            self.assertTrue(_destroyed_blueprint_cost_cleared(payload, paths))

        with patch(
            "hyops.blueprint.command.module_state_status",
            side_effect=("destroyed", "ok", "destroyed"),
        ):
            self.assertFalse(_destroyed_blueprint_cost_cleared(payload, paths))

    def test_retained_step_prevents_zero_cost_claim(self):
        payload = _payload()
        payload["steps"][0]["retain_on_destroy"] = True
        paths = SimpleNamespace(state_dir="/tmp/state")

        with patch("hyops.blueprint.command.module_state_status") as status:
            self.assertFalse(_destroyed_blueprint_cost_cleared(payload, paths))
        status.assert_not_called()

    def _run(self, statuses, run_step, *, retained=()):
        paths = SimpleNamespace(state_dir="/tmp/state", root=SimpleNamespace(name="test"))
        payload = _payload()
        for step in payload["steps"]:
            if step["id"] in retained:
                step["retain_on_destroy"] = True

        def state_status(_state_dir, state_ref):
            return statuses[state_ref.rsplit("#", 1)[-1]]

        with (
            patch("hyops.blueprint.command._resolve_and_validate", return_value=payload),
            patch("hyops.blueprint.command.require_runtime_selection"),
            patch("hyops.blueprint.command.resolve_runtime_paths", return_value=paths),
            patch("hyops.blueprint.command.ensure_layout"),
            patch("hyops.blueprint.command.require_runtime_writable"),
            patch("hyops.blueprint.command._enforce_runtime_blueprint_file_scope"),
            patch("hyops.blueprint.command.module_state_status", side_effect=state_status),
            patch("hyops.blueprint.command.resolved_step_inputs_file", return_value=None) as inputs_file,
            patch("hyops.blueprint.command.run_step_module_command", side_effect=run_step) as command,
        ):
            rc = run_destroy(_namespace())
        return rc, inputs_file, command

    def test_retained_dependency_is_not_destroyed(self):
        rc, inputs_file, command = self._run(
            {"network": "ok", "vm": "destroyed", "health": "destroyed"},
            [],
            retained=("network",),
        )

        self.assertEqual(rc, 0)
        inputs_file.assert_not_called()
        command.assert_not_called()

    def test_archive_hides_child_progress_and_restores_environment(self):
        with tempfile.TemporaryDirectory() as tmp:
            archive_path = Path(tmp) / "labs.tar.gz"
            archive_path.write_bytes(b"portable labs")
            checksum = hashlib.sha256(archive_path.read_bytes()).hexdigest()
            payload = {
                "archive_before_destroy": {
                    "module_ref": "platform/test/archive",
                    "state_instance": "lab_archive",
                    "inputs": {},
                }
            }
            paths = SimpleNamespace(state_dir=Path(tmp) / "state")
            state = {
                "outputs": {
                    "eveng_lab_archive_path": str(archive_path),
                    "eveng_lab_archive_sha256": checksum,
                }
            }

            def run_archive(*_args):
                self.assertEqual(os.environ.get("HYOPS_PROGRESS_CHILD"), "1")
                return 0

            with (
                patch("hyops.blueprint.command.run_step_module_command", side_effect=run_archive),
                patch("hyops.blueprint.command.read_module_state", return_value=state),
            ):
                os.environ.pop("HYOPS_PROGRESS_CHILD", None)
                rc = _run_archive_before_destroy(_namespace(), payload, paths)
                self.assertNotIn("HYOPS_PROGRESS_CHILD", os.environ)

        self.assertEqual(rc, 0)

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

    def test_non_interactive_archive_choice_must_be_explicit(self):
        ns = _namespace()
        payload = {"archive_before_destroy": {"module_ref": "platform/test/archive"}}

        with self.assertRaisesRegex(ValueError, "select --archive-before-destroy"):
            _select_archive_destroy_mode(ns, payload, "test")

    def test_archive_flag_requires_blueprint_lifecycle(self):
        ns = _namespace()
        ns.archive_before_destroy = True

        with self.assertRaisesRegex(ValueError, "does not declare"):
            _select_archive_destroy_mode(ns, _payload(), "test")

    def test_verified_archive_is_accepted(self):
        with tempfile.TemporaryDirectory() as tmp:
            archive_path = Path(tmp) / "labs.tar.gz"
            archive_path.write_bytes(b"portable labs")
            checksum = hashlib.sha256(archive_path.read_bytes()).hexdigest()
            payload = {
                "archive_before_destroy": {
                    "module_ref": "platform/test/archive",
                    "state_instance": "lab_archive",
                    "inputs": {},
                }
            }
            paths = SimpleNamespace(state_dir=Path(tmp) / "state")
            state = {
                "outputs": {
                    "eveng_lab_archive_path": str(archive_path),
                    "eveng_lab_archive_sha256": checksum,
                }
            }

            with (
                patch("hyops.blueprint.command.run_step_module_command", return_value=0),
                patch("hyops.blueprint.command.read_module_state", return_value=state),
            ):
                rc = _run_archive_before_destroy(_namespace(), payload, paths)

        self.assertEqual(rc, 0)

    def test_normal_archive_success_hides_paths_and_checksums(self):
        with tempfile.TemporaryDirectory() as tmp:
            archive_path = Path(tmp) / "labs.tar.gz"
            archive_path.write_bytes(b"portable labs")
            checksum = hashlib.sha256(archive_path.read_bytes()).hexdigest()
            payload = {
                "archive_before_destroy": {
                    "module_ref": "platform/test/archive",
                    "state_instance": "lab_archive",
                    "inputs": {},
                }
            }
            paths = SimpleNamespace(state_dir=Path(tmp) / "state")
            state = {
                "outputs": {
                    "eveng_lab_archive_path": str(archive_path),
                    "eveng_lab_archive_sha256": checksum,
                }
            }
            stdout = io.StringIO()

            with (
                patch("hyops.blueprint.command.run_step_module_command", return_value=0),
                patch("hyops.blueprint.command.read_module_state", return_value=state),
                patch("hyops.blueprint.command.sys.stdout", stdout),
                patch.dict(os.environ, {}, clear=True),
            ):
                rc = _run_archive_before_destroy(_namespace(), payload, paths)

        self.assertEqual(rc, 0)
        output = stdout.getvalue()
        self.assertIn("archive saved: lab definitions", output)
        self.assertNotIn(str(archive_path), output)
        self.assertNotIn(checksum, output)

    def test_failed_archive_stops_before_resource_destroy(self):
        paths = SimpleNamespace(state_dir="/tmp/state", root=SimpleNamespace(name="test"))
        payload = _payload()
        payload["archive_before_destroy"] = {
            "module_ref": "platform/test/archive",
            "state_instance": "lab_archive",
            "inputs": {"archive_action": "export"},
        }
        ns = _namespace()
        ns.archive_before_destroy = True

        with (
            patch("hyops.blueprint.command._resolve_and_validate", return_value=payload),
            patch("hyops.blueprint.command.require_runtime_selection"),
            patch("hyops.blueprint.command.resolve_runtime_paths", return_value=paths),
            patch("hyops.blueprint.command.ensure_layout"),
            patch("hyops.blueprint.command.require_runtime_writable"),
            patch("hyops.blueprint.command._enforce_runtime_blueprint_file_scope"),
            patch("hyops.blueprint.command.resolved_step_inputs_file", return_value=None),
            patch("hyops.blueprint.command.run_step_module_command", return_value=2) as command,
        ):
            rc = run_destroy(ns)

        self.assertEqual(rc, 2)
        command.assert_called_once()
        self.assertEqual(command.call_args.args[0]["id"], "archive_before_destroy")

    def test_non_interactive_destroy_requires_explicit_yes(self):
        paths = SimpleNamespace(state_dir="/tmp/state", root=SimpleNamespace(name="test"))
        ns = _namespace()
        ns.yes = False
        stdout = io.StringIO()

        with (
            patch("hyops.blueprint.command._resolve_and_validate", return_value=_payload()),
            patch("hyops.blueprint.command.require_runtime_selection"),
            patch("hyops.blueprint.command.resolve_runtime_paths", return_value=paths),
            patch("hyops.blueprint.command.ensure_layout"),
            patch("hyops.blueprint.command.require_runtime_writable"),
            patch("hyops.blueprint.command._enforce_runtime_blueprint_file_scope"),
            patch("hyops.blueprint.command.sys.stdin", io.StringIO()),
            patch("hyops.blueprint.command.sys.stdout", stdout),
            patch("hyops.blueprint.command.run_step_module_command") as command,
        ):
            rc = run_destroy(ns)

        self.assertEqual(rc, 2)
        self.assertIn("requires --yes", stdout.getvalue())
        command.assert_not_called()
