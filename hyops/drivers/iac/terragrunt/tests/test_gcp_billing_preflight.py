from unittest import TestCase
from unittest.mock import patch

from hyops.drivers.iac.terragrunt._internal.preflight import _preflight_gcp_billing


class GcpBillingPreflightTest(TestCase):
    @patch(
        "hyops.drivers.iac.terragrunt._internal.preflight.diagnose_project_billing",
        return_value=(True, True, ""),
    )
    def test_apply_allows_enabled_billing(self, diagnose):
        error = _preflight_gcp_billing(
            lifecycle_command="apply",
            module_ref="platform/gcp/lab-network",
            profile_ref="gcp@v1.0",
            runtime={},
            inputs={"project_id": "student-project"},
        )
        self.assertEqual(error, "")
        diagnose.assert_called_once_with("student-project")

    @patch(
        "hyops.drivers.iac.terragrunt._internal.preflight.diagnose_project_billing",
        return_value=(True, False, "billing disabled"),
    )
    def test_apply_blocks_disabled_billing(self, _diagnose):
        error = _preflight_gcp_billing(
            lifecycle_command="apply",
            module_ref="platform/gcp/lab-network",
            profile_ref="gcp@v1.0",
            runtime={},
            inputs={"project_id": "student-project"},
        )
        self.assertIn("billing is not enabled", error)

    @patch("hyops.drivers.iac.terragrunt._internal.preflight.diagnose_project_billing")
    def test_destroy_skips_billing_check(self, diagnose):
        error = _preflight_gcp_billing(
            lifecycle_command="destroy",
            module_ref="platform/gcp/lab-network",
            profile_ref="gcp@v1.0",
            runtime={},
            inputs={"project_id": "student-project"},
        )
        self.assertEqual(error, "")
        diagnose.assert_not_called()

    @patch("hyops.drivers.iac.terragrunt._internal.preflight.diagnose_project_billing")
    def test_non_gcp_profile_skips_billing_check(self, diagnose):
        error = _preflight_gcp_billing(
            lifecycle_command="apply",
            module_ref="platform/onprem/platform-vm",
            profile_ref="proxmox@v1.0",
            runtime={},
            inputs={},
        )
        self.assertEqual(error, "")
        diagnose.assert_not_called()
