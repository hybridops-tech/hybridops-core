from __future__ import annotations

from unittest import TestCase

from hyops.drivers.config.ansible.config import resolve_execution_timeout


class AnsibleExecutionPolicyTests(TestCase):
    def test_module_timeout_overrides_profile_default(self):
        timeout, error = resolve_execution_timeout(
            {"execution_timeout_s": 14400},
            default=3600,
        )

        self.assertEqual(timeout, 14400)
        self.assertEqual(error, "")

    def test_module_timeout_is_bounded(self):
        timeout, error = resolve_execution_timeout(
            {"execution_timeout_s": 86401},
            default=3600,
        )

        self.assertEqual(timeout, 3600)
        self.assertIn("between 60 and 86400", error)

    def test_profile_timeout_remains_default(self):
        timeout, error = resolve_execution_timeout({}, default=3600)

        self.assertEqual(timeout, 3600)
        self.assertEqual(error, "")
