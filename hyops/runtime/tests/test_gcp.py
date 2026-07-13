from unittest import TestCase
from unittest.mock import patch

from hyops.runtime.gcp import diagnose_project_billing


class ProjectBillingTest(TestCase):
    @patch("hyops.runtime.gcp._gcloud_capture", return_value=(0, "True", ""))
    def test_enabled(self, capture):
        self.assertEqual(diagnose_project_billing("student-project"), (True, True, ""))
        capture.assert_called_once()

    @patch("hyops.runtime.gcp._gcloud_capture", return_value=(0, "False", ""))
    def test_disabled(self, _capture):
        validated, enabled, detail = diagnose_project_billing("student-project")
        self.assertTrue(validated)
        self.assertFalse(enabled)
        self.assertIn("not enabled", detail)

    @patch("hyops.runtime.gcp._gcloud_capture", return_value=(1, "", "permission denied"))
    def test_inaccessible(self, _capture):
        self.assertEqual(
            diagnose_project_billing("student-project"),
            (False, False, "permission denied"),
        )

    @patch("hyops.runtime.gcp._gcloud_capture", return_value=(0, "unknown", ""))
    def test_malformed(self, _capture):
        validated, enabled, detail = diagnose_project_billing("student-project")
        self.assertFalse(validated)
        self.assertFalse(enabled)
        self.assertIn("unexpected billingEnabled value", detail)
