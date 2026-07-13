from pathlib import Path
from unittest import TestCase
from types import SimpleNamespace
from unittest.mock import patch

from hyops.init.targets.gcp import (
    _adc_impersonation_ok,
    _discover_gcp_projects,
    _ensure_terraform_sa_project_roles,
    _offer_ssh_key_generation,
    _prompt_gcp_region,
    _select_gcp_project_interactive,
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


class GcpProjectSelectionTest(TestCase):
    @patch("hyops.init.targets.gcp._cmd_stdout")
    def test_discovers_active_projects(self, cmd_stdout):
        cmd_stdout.return_value = """[
          {"projectId": "z-project", "name": "Zeta"},
          {"projectId": "a-project", "name": "Alpha"},
          {"projectId": "a-project", "name": "Duplicate"}
        ]"""

        projects = _discover_gcp_projects(Path("/tmp/evidence"))

        self.assertEqual(
            projects,
            [
                {"id": "a-project", "name": "Alpha"},
                {"id": "z-project", "name": "Zeta"},
            ],
        )
        self.assertEqual(cmd_stdout.call_args.args[0][0:3], ["gcloud", "projects", "list"])

    @patch("builtins.input", return_value="2")
    def test_selects_project_by_number(self, _input):
        selected, source = _select_gcp_project_interactive(
            [
                {"id": "a-project", "name": "Alpha"},
                {"id": "z-project", "name": "Zeta"},
            ]
        )

        self.assertEqual((selected, source), ("z-project", "prompt"))

    @patch("builtins.input", return_value="Alpha")
    def test_selects_project_by_unique_name(self, _input):
        selected, source = _select_gcp_project_interactive(
            [
                {"id": "a-project", "name": "Alpha"},
                {"id": "z-project", "name": "Zeta"},
            ]
        )

        self.assertEqual((selected, source), ("a-project", "prompt"))

    @patch("builtins.input", return_value="manual-project")
    def test_falls_back_to_manual_project_id(self, _input):
        self.assertEqual(
            _select_gcp_project_interactive([]),
            ("manual-project", "prompt"),
        )

    @patch("builtins.input", side_effect=["", "1"])
    def test_blank_project_selection_reprompts(self, _input):
        selected, source = _select_gcp_project_interactive(
            [{"id": "a-project", "name": "Alpha"}, {"id": "z-project", "name": "Zeta"}]
        )

        self.assertEqual((selected, source), ("a-project", "prompt"))


class GcpRegionPromptTest(TestCase):
    @patch("builtins.input", side_effect=["", "europe-west2"])
    def test_empty_required_region_reprompts(self, _input):
        self.assertEqual(_prompt_gcp_region(), "europe-west2")


class GcpRegionDefaultTest(TestCase):
    @patch("builtins.input", return_value="")
    def test_empty_answer_keeps_nonempty_default(self, _input):
        self.assertEqual(_prompt_gcp_region(default="europe-west2"), "europe-west2")

    @patch("builtins.input", side_effect=["europe-west2-a", "europe-west2"])
    def test_zone_is_rejected_as_region(self, _input):
        self.assertEqual(_prompt_gcp_region(), "europe-west2")


class GcpSshKeySetupTest(TestCase):
    @patch("hyops.init.targets.gcp._read_first_pubkey", return_value="ssh-ed25519 generated hybridops")
    @patch("hyops.init.targets.gcp.run_capture")
    @patch("hyops.init.targets.gcp.Path.home")
    @patch("builtins.input", return_value="")
    def test_generates_ed25519_key_by_default(self, _input, home, run_capture, _read_key):
        from tempfile import TemporaryDirectory

        with TemporaryDirectory() as tmp:
            home.return_value = Path(tmp)
            run_capture.return_value = SimpleNamespace(rc=0)

            result = _offer_ssh_key_generation(Path(tmp) / "evidence")

        self.assertEqual(result, "ssh-ed25519 generated hybridops")
        command = run_capture.call_args.args[0]
        self.assertEqual(command[0:3], ["ssh-keygen", "-t", "ed25519"])
        self.assertIn("-N", command)

    @patch("builtins.input", return_value="n")
    def test_allows_operator_to_decline_key_generation(self, _input):
        self.assertEqual(_offer_ssh_key_generation(Path("/tmp/evidence")), "")
