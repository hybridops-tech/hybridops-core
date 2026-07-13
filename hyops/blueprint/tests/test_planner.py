from pathlib import Path
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import patch

from hyops.blueprint.planner import _required_env_error, compute_preflight


class RequiredEnvironmentPreflightTest(TestCase):
    def test_missing_secrets_are_reported_before_deferred_driver_checks(self):
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
            "hyops secrets ensure --env student-lab EVENG_ADMIN_PASSWORD EVENG_ROOT_PASSWORD",
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


class PlannedDependencyPreflightTest(TestCase):
    @patch(
        "hyops.drivers.config.ansible.runtime_env.ensure_hybridops_collections_available",
        return_value="missing HybridOps Ansible collections; run: hyops setup galaxy",
    )
    def test_missing_collections_block_linux_steps(self, _collections):
        payload = {
            "order": ["config"],
            "steps": [
                {
                    "id": "config",
                    "module_ref": "platform/linux/eve-ng",
                    "action": "deploy",
                    "phase": "operations",
                    "optional": False,
                }
            ],
        }

        results, required_failures, optional_failures = compute_preflight(
            payload,
            SimpleNamespace(),
            SimpleNamespace(state_dir="/tmp/state", root=Path("/tmp/runtime")),
        )

        self.assertEqual(results[0]["status"], "blocked")
        self.assertIn("hyops setup galaxy", results[0]["checks"][0]["detail"])
        self.assertEqual(required_failures, ["ansible_controller"])
        self.assertEqual(optional_failures, [])

    @patch(
        "hyops.drivers.config.ansible.runtime_env.ensure_hybridops_collections_available",
        return_value="",
    )
    @patch("hyops.blueprint.planner.preflight_step")
    def test_remote_check_waits_for_configuration(self, preflight_step, _collections):
        payload = {
            "order": ["config", "health"],
            "steps": [
                {
                    "id": "config",
                    "module_ref": "platform/linux/eve-ng",
                    "state_instance": "student_config",
                    "action": "deploy",
                    "phase": "operations",
                    "optional": False,
                },
                {
                    "id": "health",
                    "module_ref": "platform/linux/eve-ng-healthcheck",
                    "state_instance": "student_health",
                    "action": "deploy",
                    "phase": "operations",
                    "optional": False,
                    "requires": ["config"],
                },
            ],
        }
        preflight_step.return_value = {
            "id": "config",
            "status": "ready",
            "optional": False,
        }

        results, required_failures, optional_failures = compute_preflight(
            payload,
            SimpleNamespace(),
            SimpleNamespace(state_dir="/tmp/state", root=Path("/tmp/runtime")),
        )

        self.assertEqual([item["status"] for item in results], ["ready", "ready"])
        self.assertIn("configuration runs", results[1]["checks"][0]["detail"])
        self.assertEqual(required_failures, [])
        self.assertEqual(optional_failures, [])
        preflight_step.assert_called_once()

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

    @patch(
        "hyops.drivers.config.ansible.runtime_env.ensure_hybridops_collections_available",
        return_value="",
    )
    @patch("hyops.blueprint.planner.preflight_step")
    def test_upstream_failure_defers_dependency_chain(
        self, preflight_step, _collections
    ):
        payload = {
            "order": ["network", "vm", "config"],
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
                {
                    "id": "config",
                    "module_ref": "platform/linux/eve-ng",
                    "state_instance": "student_config",
                    "action": "deploy",
                    "phase": "operations",
                    "optional": False,
                    "requires": ["vm"],
                },
            ],
        }
        preflight_step.return_value = {
            "id": "network",
            "status": "blocked",
            "optional": False,
        }

        results, required_failures, optional_failures = compute_preflight(
            payload,
            SimpleNamespace(),
            SimpleNamespace(state_dir="/tmp/state"),
        )

        self.assertEqual([item["status"] for item in results], ["blocked", "deferred", "deferred"])
        self.assertEqual(required_failures, ["network"])
        self.assertEqual(optional_failures, [])
        preflight_step.assert_called_once()
