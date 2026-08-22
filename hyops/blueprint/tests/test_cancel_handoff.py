import io
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from hyops.blueprint.command import (
    _cancelled_deploy_actions,
    _failed_deploy_has_resources,
    _offer_failed_deploy_destroy,
)


class _TTY(io.StringIO):
    def isatty(self):
        return True


class CancelledDeployActionsTests(unittest.TestCase):
    def test_commands_preserve_environment_and_blueprint_reference(self):
        ns = SimpleNamespace(env="academic-demo-gcp-2", root=None, file=None)
        payload = {"blueprint_ref": "gcp/eve-ng@v1"}

        actions = _cancelled_deploy_actions(ns, payload)

        self.assertEqual(
            actions["resume"],
            "hyops blueprint deploy --env academic-demo-gcp-2 "
            "--ref gcp/eve-ng@v1 --execute",
        )
        self.assertEqual(
            actions["destroy"],
            "hyops blueprint destroy --env academic-demo-gcp-2 "
            "--ref gcp/eve-ng@v1 --execute",
        )

    def test_commands_quote_custom_runtime_and_blueprint_paths(self):
        ns = SimpleNamespace(
            env=None,
            root="/tmp/runtime with spaces",
            file="/tmp/runtime with spaces/config/blueprints/lab.yml",
        )
        payload = {"blueprint_ref": "custom/lab@v1"}

        actions = _cancelled_deploy_actions(ns, payload)

        self.assertEqual(
            actions["resume"],
            "hyops blueprint deploy --root '/tmp/runtime with spaces' "
            "--file '/tmp/runtime with spaces/config/blueprints/lab.yml' --execute",
        )
        self.assertEqual(
            actions["destroy"],
            "hyops blueprint destroy --root '/tmp/runtime with spaces' "
            "--file '/tmp/runtime with spaces/config/blueprints/lab.yml' --execute",
        )

    def test_failed_deploy_detects_live_blueprint_state(self):
        payload = {
            "steps": [
                {
                    "module_ref": "platform/test/network",
                    "state_instance": "network",
                },
                {
                    "module_ref": "platform/test/images",
                    "state_instance": "images",
                },
            ]
        }
        paths = SimpleNamespace(state_dir="/tmp/state")

        with patch(
            "hyops.blueprint.command.module_state_status",
            side_effect=("ok", "error"),
        ):
            self.assertTrue(_failed_deploy_has_resources(payload, paths))

    def test_failed_deploy_without_resources_does_not_offer_destroy(self):
        payload = {
            "blueprint_ref": "gcp/eve-ng@v1",
            "steps": [
                {
                    "module_ref": "platform/test/network",
                    "state_instance": "network",
                }
            ],
        }
        paths = SimpleNamespace(state_dir="/tmp/state")
        ns = SimpleNamespace(env="demo-lab", root=None, file=None)

        with (
            patch("hyops.blueprint.command.module_state_status", return_value="destroyed"),
            patch("hyops.blueprint.command.run_destroy") as destroy,
        ):
            self.assertEqual(_offer_failed_deploy_destroy(ns, payload, paths), 0)

        destroy.assert_not_called()

    def test_interactive_failed_deploy_uses_standard_destroy_flow(self):
        payload = {
            "blueprint_ref": "gcp/eve-ng@v1",
            "steps": [
                {
                    "module_ref": "platform/test/network",
                    "state_instance": "network",
                }
            ],
        }
        paths = SimpleNamespace(state_dir="/tmp/state")
        ns = SimpleNamespace(env="demo-lab", root=None, file=None)

        with (
            patch("hyops.blueprint.command.module_state_status", return_value="ok"),
            patch("hyops.blueprint.command.sys.stdin", _TTY()),
            patch("hyops.blueprint.command.sys.stdout", _TTY()),
            patch("hyops.blueprint.command.run_destroy", return_value=0) as destroy,
        ):
            self.assertEqual(_offer_failed_deploy_destroy(ns, payload, paths), 0)

        destroy_ns = destroy.call_args.args[0]
        self.assertTrue(destroy_ns.execute)
        self.assertFalse(destroy_ns.yes)
        self.assertFalse(destroy_ns.archive_before_destroy)
        self.assertFalse(destroy_ns.skip_archive)

    def test_non_interactive_failed_deploy_prints_destroy_command(self):
        payload = {
            "blueprint_ref": "gcp/eve-ng@v1",
            "steps": [
                {
                    "module_ref": "platform/test/network",
                    "state_instance": "network",
                }
            ],
        }
        paths = SimpleNamespace(state_dir="/tmp/state")
        ns = SimpleNamespace(env="demo-lab", root=None, file=None)
        output = io.StringIO()

        with (
            patch("hyops.blueprint.command.module_state_status", return_value="ok"),
            patch("hyops.blueprint.command.sys.stdin", io.StringIO()),
            patch("hyops.blueprint.command.sys.stdout", output),
            patch("hyops.blueprint.command.run_destroy") as destroy,
        ):
            self.assertEqual(_offer_failed_deploy_destroy(ns, payload, paths), 0)

        self.assertIn(
            "hyops blueprint destroy --env demo-lab --ref gcp/eve-ng@v1 --execute",
            output.getvalue(),
        )
        destroy.assert_not_called()


if __name__ == "__main__":
    unittest.main()
