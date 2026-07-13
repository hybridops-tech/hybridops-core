from pathlib import Path
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import patch

from hyops.blueprint.planner import _required_env_error, compute_preflight


class RequiredEnvironmentPreflightTest(TestCase):
    def test_missing_secrets_include_recovery_command(self):
        with patch.dict("hyops.blueprint.planner.os.environ", {}, clear=True):
            error = _required_env_error(
                inputs={
                    "required_env": ["EVENG_ROOT_PASSWORD", "EVENG_ADMIN_PASSWORD"],
                    "load_vault_env": True,
                },
                action="deploy",
                env_name="student-lab",
                runtime_root=Path("/tmp/hyops-required-env-test"),
            )

        self.assertIn("EVENG_ADMIN_PASSWORD, EVENG_ROOT_PASSWORD", error)
        self.assertIn(
            "hyops secrets ensure --env student-lab "
            "EVENG_ADMIN_PASSWORD EVENG_ROOT_PASSWORD",
            error,
        )

    def test_destroy_does_not_require_deploy_secrets(self):
        error = _required_env_error(
            inputs={
                "required_env": ["EVENG_ROOT_PASSWORD"],
                "required_env_destroy": [],
            },
            action="destroy",
            env_name="student-lab",
            runtime_root=Path("/tmp/hyops-required-env-test"),
        )
        self.assertEqual(error, "")

    def test_vault_backed_values_satisfy_requirement(self):
        def load_vault(env, _runtime_root):
            env["EVENG_ROOT_PASSWORD"] = "stored"
            return {"EVENG_ROOT_PASSWORD": "stored"}, ""

        with patch.dict(
            "hyops.blueprint.planner.os.environ", {}, clear=True
        ), patch(
            "hyops.blueprint.planner.merge_vault_env", side_effect=load_vault
        ):
            error = _required_env_error(
                inputs={"required_env": ["EVENG_ROOT_PASSWORD"]},
                action="deploy",
                env_name="student-lab",
                runtime_root=Path("/tmp/hyops-required-env-test"),
            )
        self.assertEqual(error, "")


class PlannedDependencyPreflightTest(TestCase):
    @patch("hyops.blueprint.planner.module_state_ok", return_value=True)
    @patch("hyops.blueprint.planner.preflight_step")
    def test_changed_upstream_state_defers_downstream_checks(
        self,
        preflight_step,
        _module_state_ok,
    ):
        payload = {
            "order": ["network", "vm"],
            "steps": [
                {
                    "id": "network",
                    "module_ref": "platform/gcp/lab-network",
                    "state_instance": "student_network",
                    "action": "deploy",
                    "phase": "bootstrap",
                    "optional": False,
                },
                {
                    "id": "vm",
                    "module_ref": "platform/gcp/platform-vm",
                    "state_instance": "student_vm",
                    "action": "deploy",
                    "phase": "bootstrap",
                    "optional": False,
                    "requires": ["network"],
                },
            ],
        }
        preflight_step.side_effect = [
            {"id": "network", "status": "ready", "optional": False},
            {"id": "vm", "status": "ready", "optional": False},
        ]

        results, required_failures, optional_failures = compute_preflight(
            payload,
            SimpleNamespace(),
            SimpleNamespace(state_dir="/tmp/state"),
        )

        self.assertEqual([item["status"] for item in results], ["ready", "ready"])
        self.assertEqual(required_failures, [])
        self.assertEqual(optional_failures, [])
        vm_call = preflight_step.call_args_list[1]
        self.assertEqual(
            vm_call.kwargs["deferred_driver_preflight_refs"],
            {"platform/gcp/lab-network#student_network"},
        )
