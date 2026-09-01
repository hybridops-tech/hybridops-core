import io
import hashlib
import os
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import patch

from hyops.blueprint.command import (
    _confirm_archive_destroy,
    _confirm_guest_quiescence,
    _destroyed_blueprint_cost_cleared,
    _gcp_blueprint_cost_estimate,
    _quiescence_action_path,
    _run_archive_before_destroy,
    _select_archive_destroy_mode,
    run_quiescence,
    run_destroy,
)
from hyops.runtime.cost import CostEstimate
from hyops.runtime.exitcodes import CANCELLED


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
        guest_quiesced=False,
        quiesce_script="",
        quiesce_timeout=None,
    )


class ResumableBlueprintDestroyTest(TestCase):
    def test_archive_destroy_confirmation_reprompts_until_exact_match(self):
        with patch(
            "hyops.blueprint.command.input",
            side_effect=["test", "destroy test"],
        ) as prompt:
            confirmed = _confirm_archive_destroy("test")

        self.assertTrue(confirmed)
        self.assertEqual(prompt.call_count, 2)

    def test_archive_destroy_confirmation_interrupt_cancels(self):
        with patch(
            "hyops.blueprint.command.input",
            side_effect=KeyboardInterrupt,
        ):
            confirmed = _confirm_archive_destroy("test")

        self.assertIsNone(confirmed)

    def test_node_state_archive_requires_quiescence_for_automatic_destroy(self):
        ns = _namespace()
        payload = {
            "archive_before_destroy": {
                "inputs": {"eveng_lab_archive_include_node_state": True}
            }
        }

        with tempfile.TemporaryDirectory() as tmp:
            paths = SimpleNamespace(
                root=Path(tmp),
                config_dir=Path(tmp) / "config",
            )
            with self.assertRaisesRegex(ValueError, "requires a configured"):
                _confirm_guest_quiescence(ns, payload, paths)

    def test_interactive_node_state_archive_records_quiescence(self):
        ns = _namespace()
        ns.yes = False
        payload = {
            "archive_before_destroy": {
                "inputs": {"eveng_lab_archive_include_node_state": True}
            }
        }

        with tempfile.TemporaryDirectory() as tmp:
            paths = SimpleNamespace(
                root=Path(tmp),
                config_dir=Path(tmp) / "config",
            )
            with (
                patch("hyops.blueprint.command.sys.stdin.isatty", return_value=True),
                patch("hyops.blueprint.command.sys.stdout.isatty", return_value=True),
                patch("hyops.blueprint.command.input", return_value="y"),
            ):
                confirmed = _confirm_guest_quiescence(ns, payload, paths)

        self.assertTrue(confirmed)
        self.assertEqual(ns._quiescence_source, "operator-attestation")

    def test_quiescence_script_satisfies_automatic_destroy_gate(self):
        ns = _namespace()
        payload = {
            "archive_before_destroy": {
                "inputs": {"eveng_lab_archive_include_node_state": True}
            }
        }
        with tempfile.TemporaryDirectory() as tmp:
            script = Path(tmp) / "quiesce.sh"
            script.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
            ns.quiesce_script = str(script)
            paths = SimpleNamespace(
                root=Path(tmp),
                config_dir=Path(tmp) / "config",
            )

            confirmed = _confirm_guest_quiescence(ns, payload, paths)

        self.assertTrue(confirmed)
        self.assertEqual(ns.quiesce_script, str(script.resolve()))
        self.assertEqual(ns._quiescence_source, "command-override")

    def test_environment_quiescence_action_is_resolved_automatically(self):
        ns = _namespace()
        payload = {
            "blueprint_ref": "gcp/eve-ng@v1",
            "archive_before_destroy": {
                "inputs": {"eveng_lab_archive_include_node_state": True}
            },
        }
        with tempfile.TemporaryDirectory() as tmp:
            paths = SimpleNamespace(
                root=Path(tmp),
                config_dir=Path(tmp) / "config",
            )
            action = _quiescence_action_path(paths, payload)
            action.parent.mkdir(parents=True)
            action.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")

            confirmed = _confirm_guest_quiescence(ns, payload, paths)

        self.assertTrue(confirmed)
        self.assertEqual(ns.quiesce_script, str(action.resolve()))
        self.assertEqual(ns._quiescence_source, "environment")

    def test_quiescence_edit_activates_valid_environment_action(self):
        ns = _namespace()
        ns.quiescence_cmd = "edit"
        payload = {
            "blueprint_ref": "gcp/eve-ng@v1",
            "archive_before_destroy": {
                "inputs": {"eveng_lab_archive_include_node_state": True}
            },
        }
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            paths = SimpleNamespace(root=root, config_dir=root / "config")
            action = _quiescence_action_path(paths, payload)
            editor = root / "editor.sh"
            editor.write_text(
                "#!/bin/sh\nprintf '#!/bin/sh\\nset -eu\\nexit 0\\n' > \"$1\"\n",
                encoding="utf-8",
            )
            editor.chmod(0o700)
            ns.editor = str(editor)

            with patch(
                "hyops.blueprint.command._quiescence_context",
                return_value=(paths, payload, action),
            ):
                rc = run_quiescence(ns)

            self.assertEqual(rc, 0)
            self.assertTrue(action.is_file())
            self.assertEqual(action.stat().st_mode & 0o777, 0o600)
            self.assertNotIn(
                "NOT_CONFIGURED",
                action.read_text(encoding="utf-8"),
            )

    def test_quiescence_edit_rejects_unchanged_template(self):
        ns = _namespace()
        ns.quiescence_cmd = "edit"
        payload = {
            "blueprint_ref": "gcp/eve-ng@v1",
            "archive_before_destroy": {
                "inputs": {"eveng_lab_archive_include_node_state": True}
            },
        }
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            paths = SimpleNamespace(root=root, config_dir=root / "config")
            action = _quiescence_action_path(paths, payload)
            editor = root / "editor.sh"
            editor.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
            editor.chmod(0o700)
            ns.editor = str(editor)

            with patch(
                "hyops.blueprint.command._quiescence_context",
                return_value=(paths, payload, action),
            ):
                rc = run_quiescence(ns)

            self.assertNotEqual(rc, 0)
            self.assertFalse(action.exists())
            self.assertTrue(action.with_suffix(".sh.draft").is_file())

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

    def test_child_destroy_is_deferred_until_parent_is_destroyed(self):
        paths = SimpleNamespace(
            state_dir=Path("/tmp/state"),
            root=SimpleNamespace(name="test"),
        )
        payload = _payload()
        payload["steps"][2]["destroy_subsumed_by"] = "vm"
        statuses = {"network": "destroyed", "vm": "ok", "health": "error"}

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
            patch(
                "hyops.blueprint.command.read_module_state",
                return_value={"status": "error"},
            ),
            patch("hyops.blueprint.command.write_module_state") as write_state,
            patch("hyops.blueprint.command.resolved_step_inputs_file", return_value=None),
            patch("hyops.blueprint.command.run_step_module_command", return_value=0) as command,
        ):
            rc = run_destroy(_namespace())

        self.assertEqual(rc, 0)
        self.assertEqual([call.args[0]["id"] for call in command.call_args_list], ["vm"])
        self.assertEqual(write_state.call_args.args[2]["status"], "destroyed")
        self.assertEqual(
            write_state.call_args.args[2]["destroyed_by_blueprint_step"],
            "vm",
        )

    def test_subsumed_child_is_not_destroyed_when_parent_fails(self):
        paths = SimpleNamespace(
            state_dir=Path("/tmp/state"),
            root=SimpleNamespace(name="test"),
        )
        payload = _payload()
        payload["steps"][2]["destroy_subsumed_by"] = "vm"
        statuses = {"network": "ok", "vm": "ok", "health": "error"}

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
            patch("hyops.blueprint.command.write_module_state") as write_state,
            patch("hyops.blueprint.command.resolved_step_inputs_file", return_value=None),
            patch("hyops.blueprint.command.run_step_module_command", return_value=2),
        ):
            rc = run_destroy(_namespace())

        self.assertEqual(rc, 2)
        write_state.assert_not_called()

    def test_destroy_gate_runs_when_required_step_is_live(self):
        paths = SimpleNamespace(state_dir="/tmp/state", root=SimpleNamespace(name="test"))
        payload = _payload()
        payload["steps"][2]["destroy_gate"] = True
        payload["steps"][2]["requires"] = ["vm"]
        statuses = {
            "network": "destroyed",
            "vm": "ok",
            "health": "absent",
        }

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
            patch("hyops.blueprint.command.resolved_step_inputs_file", return_value=None),
            patch("hyops.blueprint.command.run_step_module_command", return_value=0) as command,
        ):
            rc = run_destroy(_namespace())

        self.assertEqual(rc, 0)
        self.assertEqual(
            [call.args[0]["id"] for call in command.call_args_list],
            ["health", "vm"],
        )

    def test_destroy_runs_step_left_error_by_failed_apply(self):
        rc, inputs_file, command = self._run(
            {"network": "error", "vm": "destroyed", "health": "destroyed"},
            [0],
        )

        self.assertEqual(rc, 0)
        self.assertEqual(inputs_file.call_count, 1)
        self.assertEqual(command.call_count, 1)
        self.assertEqual(command.call_args.args[0]["id"], "network")

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

    def test_archive_choice_reprompts_until_an_exact_selection(self):
        ns = _namespace()
        ns.yes = False
        payload = {"archive_before_destroy": {"module_ref": "platform/test/archive"}}

        with (
            patch("hyops.blueprint.command.sys.stdin.isatty", return_value=True),
            patch("hyops.blueprint.command.sys.stdout.isatty", return_value=True),
            patch(
                "hyops.blueprint.command.input",
                side_effect=["31", "", "2"],
            ) as prompt,
        ):
            selected = _select_archive_destroy_mode(ns, payload, "test")

        self.assertEqual(selected, "archive")
        self.assertEqual(prompt.call_count, 3)

    def test_archive_choice_describes_preservation_without_extra_mode(self):
        ns = _namespace()
        ns.yes = False
        payload = {"archive_before_destroy": {"module_ref": "platform/test/archive"}}

        with (
            patch("hyops.blueprint.command.sys.stdin.isatty", return_value=True),
            patch("hyops.blueprint.command.sys.stdout.isatty", return_value=True),
            patch("hyops.blueprint.command.input", return_value="1"),
            patch("builtins.print") as output,
        ):
            selected = _select_archive_destroy_mode(ns, payload, "test")

        self.assertEqual(selected, "keep")
        output.assert_any_call("  2. Preserve saved lab state, then destroy")
        output.assert_any_call("  3. Destroy without preserving lab state")

    def test_archive_choice_interrupt_is_a_distinct_cancellation(self):
        ns = _namespace()
        ns.yes = False
        payload = {"archive_before_destroy": {"module_ref": "platform/test/archive"}}

        with (
            patch("hyops.blueprint.command.sys.stdin.isatty", return_value=True),
            patch("hyops.blueprint.command.sys.stdout.isatty", return_value=True),
            patch("hyops.blueprint.command.input", side_effect=KeyboardInterrupt),
        ):
            selected = _select_archive_destroy_mode(ns, payload, "test")

        self.assertEqual(selected, "cancel")

    def test_cancelled_archive_choice_returns_cancelled_without_destroying(self):
        paths = SimpleNamespace(
            state_dir=Path("/tmp/state"),
            root=SimpleNamespace(name="test"),
        )
        payload = _payload()
        payload["archive_before_destroy"] = {
            "module_ref": "platform/test/archive",
            "state_instance": "lab_archive",
            "inputs": {},
        }

        with (
            patch("hyops.blueprint.command._resolve_and_validate", return_value=payload),
            patch("hyops.blueprint.command.require_runtime_selection"),
            patch("hyops.blueprint.command.resolve_runtime_paths", return_value=paths),
            patch("hyops.blueprint.command.ensure_layout"),
            patch("hyops.blueprint.command.require_runtime_writable"),
            patch("hyops.blueprint.command._enforce_runtime_blueprint_file_scope"),
            patch(
                "hyops.blueprint.command._select_archive_destroy_mode",
                return_value="cancel",
            ),
            patch("hyops.blueprint.command.run_step_module_command") as command,
        ):
            rc = run_destroy(_namespace())

        self.assertEqual(rc, CANCELLED)
        command.assert_not_called()

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

    def test_archive_reports_retained_previous_generation(self):
        with tempfile.TemporaryDirectory() as tmp:
            archive_path = Path(tmp) / "labs.tar.gz"
            previous_path = Path(tmp) / "labs.tar.gz.previous"
            archive_path.write_bytes(b"current labs")
            previous_path.write_bytes(b"previous labs")
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
                    "eveng_lab_archive_previous_path": str(previous_path),
                    "eveng_lab_archive_sha256": checksum,
                }
            }
            stdout = io.StringIO()

            with (
                patch("hyops.blueprint.command.run_step_module_command", return_value=0),
                patch("hyops.blueprint.command.read_module_state", return_value=state),
                patch("hyops.blueprint.command.sys.stdout", stdout),
            ):
                rc = _run_archive_before_destroy(_namespace(), payload, paths)

        self.assertEqual(rc, 0)
        self.assertIn("previous generation retained", stdout.getvalue())

    def test_archive_reports_saved_device_configurations(self):
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
                    "eveng_lab_archive_device_configs_captured": True,
                }
            }
            stdout = io.StringIO()

            with (
                patch("hyops.blueprint.command.run_step_module_command", return_value=0),
                patch("hyops.blueprint.command.read_module_state", return_value=state),
                patch("hyops.blueprint.command.sys.stdout", stdout),
            ):
                rc = _run_archive_before_destroy(_namespace(), payload, paths)

        self.assertEqual(rc, 0)
        self.assertIn(
            "archive saved: lab definitions, saved device configurations",
            stdout.getvalue(),
        )

    def test_archive_reports_absent_qemu_node_state(self):
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
                    "eveng_lab_archive_node_state_included": False,
                }
            }
            stdout = io.StringIO()

            with (
                patch("hyops.blueprint.command.run_step_module_command", return_value=0),
                patch("hyops.blueprint.command.read_module_state", return_value=state),
                patch("hyops.blueprint.command.sys.stdout", stdout),
            ):
                rc = _run_archive_before_destroy(_namespace(), payload, paths)

        self.assertEqual(rc, 0)
        self.assertIn("node state: no QEMU overlays found", stdout.getvalue())

    def test_archive_execution_injects_guest_quiescence(self):
        payload = {
            "archive_before_destroy": {
                "module_ref": "platform/linux/eve-ng-lab-archive",
                "state_instance": "lab_archive",
                "inputs": {
                    "eveng_lab_archive_include_node_state": True,
                    "eveng_lab_archive_stop_running_nodes": True,
                },
            }
        }
        ns = _namespace()
        ns.guest_quiesced = True
        paths = SimpleNamespace(state_dir=Path("/tmp/state"))

        with patch(
            "hyops.blueprint.command.run_step_module_command",
            return_value=CANCELLED,
        ) as command:
            rc = _run_archive_before_destroy(ns, payload, paths)

        self.assertEqual(rc, CANCELLED)
        inputs = command.call_args.args[0]["inputs"]
        self.assertTrue(inputs["eveng_lab_archive_guest_quiesced"])
        self.assertTrue(inputs["eveng_lab_archive_stop_running_nodes"])

    def test_archive_execution_injects_quiescence_script(self):
        payload = {
            "archive_before_destroy": {
                "module_ref": "platform/linux/eve-ng-lab-archive",
                "state_instance": "lab_archive",
                "inputs": {"eveng_lab_archive_include_node_state": True},
            }
        }
        ns = _namespace()
        ns.quiesce_script = "/tmp/quiesce.sh"
        ns.quiesce_timeout = 120
        paths = SimpleNamespace(state_dir=Path("/tmp/state"))

        with patch(
            "hyops.blueprint.command.run_step_module_command",
            return_value=CANCELLED,
        ) as command:
            rc = _run_archive_before_destroy(ns, payload, paths)

        self.assertEqual(rc, CANCELLED)
        inputs = command.call_args.args[0]["inputs"]
        self.assertFalse(inputs["eveng_lab_archive_guest_quiesced"])
        self.assertEqual(
            inputs["eveng_lab_archive_quiesce_script_path"],
            "/tmp/quiesce.sh",
        )
        self.assertEqual(inputs["eveng_lab_archive_quiesce_timeout_s"], 120)

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

    def test_interrupted_archive_reports_retained_resources(self):
        payload = {
            "archive_before_destroy": {
                "module_ref": "platform/test/archive",
                "state_instance": "lab_archive",
                "inputs": {},
            }
        }
        paths = SimpleNamespace(state_dir=Path("/tmp/state"))
        stdout = io.StringIO()

        with (
            patch(
                "hyops.blueprint.command.run_step_module_command",
                side_effect=KeyboardInterrupt,
            ),
            patch("hyops.blueprint.command.sys.stdout", stdout),
        ):
            rc = _run_archive_before_destroy(_namespace(), payload, paths)

        self.assertEqual(rc, CANCELLED)
        output = stdout.getvalue()
        self.assertIn("Archive interrupted. Resources were retained.", output)
        self.assertIn("Check lab state before continuing.", output)

    def test_cancelled_archive_stops_before_resource_destroy(self):
        paths = SimpleNamespace(state_dir="/tmp/state", root=SimpleNamespace(name="test"))
        payload = _payload()
        payload["archive_before_destroy"] = {
            "module_ref": "platform/test/archive",
            "state_instance": "lab_archive",
            "inputs": {"archive_action": "export"},
        }
        ns = _namespace()
        ns.archive_before_destroy = True
        stdout = io.StringIO()

        with (
            patch("hyops.blueprint.command._resolve_and_validate", return_value=payload),
            patch("hyops.blueprint.command.require_runtime_selection"),
            patch("hyops.blueprint.command.resolve_runtime_paths", return_value=paths),
            patch("hyops.blueprint.command.ensure_layout"),
            patch("hyops.blueprint.command.require_runtime_writable"),
            patch("hyops.blueprint.command._enforce_runtime_blueprint_file_scope"),
            patch("hyops.blueprint.command.resolved_step_inputs_file", return_value=None),
            patch(
                "hyops.blueprint.command.run_step_module_command",
                return_value=CANCELLED,
            ) as command,
            patch("hyops.blueprint.command.sys.stdout", stdout),
        ):
            rc = run_destroy(ns)

        self.assertEqual(rc, CANCELLED)
        command.assert_called_once()
        self.assertEqual(command.call_args.args[0]["id"], "archive_before_destroy")
        self.assertIn("Archive interrupted. Resources were retained.", stdout.getvalue())

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
