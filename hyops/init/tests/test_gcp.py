from pathlib import Path
from unittest import TestCase
from unittest.mock import patch

from hyops.init.targets.gcp import _adc_impersonation_ok


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
