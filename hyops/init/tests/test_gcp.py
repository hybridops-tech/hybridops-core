from pathlib import Path
from unittest import TestCase
from types import SimpleNamespace
from unittest.mock import patch

from hyops.init.targets.gcp import (
    _adc_impersonation_ok,
    _ensure_terraform_sa_project_roles,
)


class AdcImpersonationTest(TestCase):
    @patch("hyops.init.targets.gcp._shell_ok", return_value=True)
    def test_uses_application_default_credentials(self, shell_ok):
        evidence_dir = Path("/tmp/evidence")

        result = _adc_impersonation_ok(
            terraform_sa_email="terraform@example.iam.gserviceaccount.com",
            project_id="student-project",
            evidence_dir=evidence_dir,
            label="adc_impersonation_check",
        )

        self.assertTrue(result)
        command, actual_evidence_dir, label = shell_ok.call_args.args
        self.assertIn("gcloud auth application-default print-access-token", command)
        self.assertIn(
            "--impersonate-service-account=terraform@example.iam.gserviceaccount.com",
            command,
        )
        self.assertIn("--project=student-project", command)
        self.assertEqual(actual_evidence_dir, evidence_dir)
        self.assertEqual(label, "adc_impersonation_check")

    @patch("hyops.init.targets.gcp._shell_ok", return_value=False)
    def test_propagates_adc_impersonation_failure(self, shell_ok):
        result = _adc_impersonation_ok(
            terraform_sa_email="terraform@example.iam.gserviceaccount.com",
            project_id="student-project",
            evidence_dir=Path("/tmp/evidence"),
            label="adc_impersonation_check",
        )

        self.assertFalse(result)
        shell_ok.assert_called_once()


class TerraformServiceAccountSetupTest(TestCase):
    @patch("hyops.init.targets.gcp.diagnose_private_service_access_permissions", return_value=(True, ""))
    @patch("hyops.init.targets.gcp.run_capture")
    def test_enables_compute_and_iap_apis(self, run_capture, _diagnose):
        run_capture.return_value = SimpleNamespace(rc=0, stderr="")
        evidence_dir = Path("/tmp/evidence")

        _ensure_terraform_sa_project_roles(
            project_id="student-project",
            terraform_sa_email="terraform@example.iam.gserviceaccount.com",
            evidence_dir=evidence_dir,
        )

        commands = [entry.args[0] for entry in run_capture.call_args_list]
        self.assertIn(
            ["gcloud", "services", "enable", "compute.googleapis.com", "--project", "student-project"],
            commands,
        )
        self.assertIn(
            ["gcloud", "services", "enable", "iap.googleapis.com", "--project", "student-project"],
            commands,
        )
