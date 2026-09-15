"""Contract tests for the EVE-NG module execution pack."""

from pathlib import Path
from unittest import TestCase

import yaml


class EVENGModuleTest(TestCase):
    def setUp(self) -> None:
        root = Path(__file__).resolve().parents[2]
        self.playbook_path = (
            root
            / "packs/config/ansible/linux/common/platform/"
            "40-eve-ng@v1.0/stack/playbook.yml"
        )
        self.play = yaml.safe_load(self.playbook_path.read_text(encoding="utf-8"))[0]

    def test_user_passwords_are_resolved_without_logging(self) -> None:
        task = next(
            item
            for item in self.play["tasks"]
            if item["name"] == "Resolve EVE-NG user passwords"
        )

        self.assertTrue(task["no_log"])
        expression = task["ansible.builtin.set_fact"][
            "_hyops_resolved_eveng_users"
        ]
        self.assertIn("lookup('env', item.password_env)", expression)
        self.assertIn("item.password", expression)

    def test_role_receives_only_resolved_users(self) -> None:
        role_task = next(
            item
            for item in self.play["tasks"]
            if item["name"] == "Install and configure EVE-NG"
        )

        self.assertEqual(
            role_task["vars"]["eveng_users"],
            "{{ _hyops_resolved_eveng_users }}",
        )


if __name__ == "__main__":
    import unittest

    unittest.main()
