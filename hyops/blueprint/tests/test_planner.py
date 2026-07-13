from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import patch

from hyops.blueprint.planner import compute_preflight


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
