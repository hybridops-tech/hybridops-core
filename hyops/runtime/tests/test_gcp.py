from unittest import TestCase
from unittest.mock import patch
from pathlib import Path
from tempfile import TemporaryDirectory

from hyops.runtime.gcp import diagnose_project_billing
from hyops.runtime.module_state_contracts import resolve_gcp_vm_zone_from_init
from hyops.runtime.readiness import write_marker


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


class GcpVmZoneResolutionTest(TestCase):
    def test_uses_initialized_zone(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            state_root = root / "state"
            write_marker(
                root / "meta",
                "gcp",
                {
                    "status": "ready",
                    "context": {
                        "region": "europe-west2",
                        "zone": "europe-west2-b",
                    },
                },
            )
            inputs = {"zone": "", "zone_from_init_region": True}

            resolve_gcp_vm_zone_from_init(inputs, state_root=state_root)

        self.assertEqual(inputs["zone"], "europe-west2-b")

    def test_derives_zone_from_initialized_region(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            state_root = root / "state"
            write_marker(root / "meta", "gcp", {"status": "ready", "context": {"region": "europe-west2"}})
            inputs = {"zone": "", "zone_from_init_region": True}

            resolve_gcp_vm_zone_from_init(inputs, state_root=state_root)

        self.assertEqual(inputs["zone"], "europe-west2-a")

    def test_rejects_zone_outside_initialized_region(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            state_root = root / "state"
            write_marker(root / "meta", "gcp", {"status": "ready", "context": {"region": "europe-west2"}})

            with self.assertRaisesRegex(ValueError, "does not belong"):
                resolve_gcp_vm_zone_from_init(
                    {"zone": "us-central1-a", "zone_from_init_region": True},
                    state_root=state_root,
                )
