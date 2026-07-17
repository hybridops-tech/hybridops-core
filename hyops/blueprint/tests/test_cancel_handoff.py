from types import SimpleNamespace
import unittest

from hyops.blueprint.command import _cancelled_deploy_actions


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


if __name__ == "__main__":
    unittest.main()
