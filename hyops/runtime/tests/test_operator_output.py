"""Tests for concise operator-facing error messages."""

from __future__ import annotations

import unittest

from hyops.runtime.operator_output import concise_error


class OperatorOutputTests(unittest.TestCase):
    def test_configuration_failure_hides_driver_and_log_filename(self) -> None:
        message = concise_error(
            "ansible apply failed "
            "(open: /tmp/run/platform/ansible.log)"
        )

        self.assertEqual(message, "configuration apply failed")

    def test_infrastructure_failure_uses_public_lifecycle_term(self) -> None:
        message = concise_error(
            "terragrunt destroy failed "
            "(open: /tmp/run/platform/terragrunt.log)"
        )

        self.assertEqual(message, "infrastructure teardown failed")

    def test_actionable_detail_is_preserved(self) -> None:
        message = concise_error("packer build failed: insufficient disk space")

        self.assertEqual(message, "image build failed: insufficient disk space")


if __name__ == "__main__":
    unittest.main()
