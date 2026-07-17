import argparse
from pathlib import Path
from unittest import TestCase
from types import SimpleNamespace
from unittest.mock import patch

from hyops.init.targets.gcp import (
    _adc_impersonation_ok,
    _discover_gcp_zones,
    _discover_gcp_projects,
    _cmd_ok,
    _confirm_gcp_identity_interactive,
    _ensure_terraform_sa_project_roles,
    _offer_ssh_key_generation,
    _prompt_gcp_region,
    _run_interactive_adc_login,
    _review_detected_gcp_defaults_interactive,
    _select_billing_account_interactive,
    _select_gcp_project_interactive,
    _select_gcp_zone_interactive,
    _write_config_template,
    add_subparser,
)


class GcpCommandBoundaryTest(TestCase):
    @patch("hyops.init.targets.gcp.run_capture", side_effect=FileNotFoundError("gcloud"))
    def test_missing_command_is_reported_without_traceback(self, _run_capture):
        self.assertFalse(_cmd_ok(["gcloud", "--version"], Path("/tmp/evidence"), "gcloud_version"))


class GcpCliCompatibilityTest(TestCase):
    def _parser(self):
        parser = argparse.ArgumentParser()
        add_subparser(parser.add_subparsers(dest="target"))
        return parser

    def test_accepts_neutral_runtime_options(self):
        ns = self._parser().parse_args(
            [
                "gcp",
                "--runtime-sa-email",
                "runtime@example.iam.gserviceaccount.com",
                "--quota-project-id",
                "quota-project",
                "--credentials-out",
                "/tmp/gcp.credentials",
            ]
        )

        self.assertEqual(ns.runtime_sa_email, "runtime@example.iam.gserviceaccount.com")
        self.assertEqual(ns.quota_project_id, "quota-project")
        self.assertEqual(ns.credentials_out, "/tmp/gcp.credentials")

    def test_retains_legacy_option_aliases(self):
        ns = self._parser().parse_args(
            [
                "gcp",
                "--terraform-sa-email",
                "legacy@example.iam.gserviceaccount.com",
                "--adc-quota-project-id",
                "legacy-quota",
                "--tfvars-out",
                "/tmp/legacy.tfvars",
            ]
        )

        self.assertEqual(ns.runtime_sa_email, "legacy@example.iam.gserviceaccount.com")
        self.assertEqual(ns.quota_project_id, "legacy-quota")
        self.assertEqual(ns.credentials_out, "/tmp/legacy.tfvars")

    def test_new_config_template_uses_neutral_names(self):
        from tempfile import TemporaryDirectory

        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "gcp.conf"
            _write_config_template(path)
            content = path.read_text(encoding="utf-8")

        self.assertIn("GCP_RUNTIME_SA_EMAIL=", content)
        self.assertIn("GCP_QUOTA_PROJECT_ID=", content)
        self.assertIn("GCP_CREDENTIALS_OUT=", content)
        self.assertNotIn("GCP_TERRAFORM_SA_EMAIL=", content)


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


class GcpCredentialLoginTest(TestCase):
    @patch("hyops.init.targets.gcp.run_capture_interactive")
    @patch("hyops.init.targets.gcp._require_tty", return_value=True)
    def test_avoids_quota_project_prompt_before_project_selection(self, _tty, run_interactive):
        run_interactive.return_value = SimpleNamespace(rc=0)

        result = _run_interactive_adc_login(
            Path("/tmp/evidence"),
            reason="GCP application credentials are required for initialization.",
        )

        self.assertTrue(result)
        command = run_interactive.call_args.args[0]
        self.assertIn("--disable-quota-project", command)
        self.assertIn("--no-launch-browser", command)


class GcpIdentityConfirmationTest(TestCase):
    @patch("hyops.init.targets.gcp._cmd_stdout", return_value="new@example.com")
    @patch("hyops.init.targets.gcp.run_capture_interactive")
    @patch("builtins.input", side_effect=["n", "y", "y"])
    def test_rejected_identity_can_be_replaced_without_revocation(
        self, _input, run_interactive, _cmd_stdout
    ):
        run_interactive.return_value = SimpleNamespace(rc=0)

        account, rc = _confirm_gcp_identity_interactive(
            active_account="old@example.com",
            env_name="academic-demo",
            evidence_dir=Path("/tmp/evidence"),
        )

        self.assertEqual((account, rc), ("new@example.com", 0))
        command = run_interactive.call_args.args[0]
        self.assertIn("--force", command)
        self.assertIn("--update-adc", command)
        self.assertNotIn("revoke", command)

    @patch("hyops.init.targets.gcp.run_capture_interactive")
    @patch("builtins.input", side_effect=["n", "n"])
    def test_rejected_identity_can_cancel_without_change(self, _input, run_interactive):
        account, rc = _confirm_gcp_identity_interactive(
            active_account="old@example.com",
            env_name="academic-demo",
            evidence_dir=Path("/tmp/evidence"),
        )

        self.assertEqual(account, "")
        self.assertNotEqual(rc, 0)
        run_interactive.assert_not_called()


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


class GcpBillingAccountSelectionTest(TestCase):
    @patch("builtins.input", side_effect=["", "1"])
    def test_billing_account_cannot_be_skipped_for_new_project(self, _input):
        selected, source = _select_billing_account_interactive(
            [
                {"id": "ABC-123", "display_name": "Teaching"},
                {"id": "XYZ-789", "display_name": "Research"},
            ]
        )

        self.assertEqual((selected, source), ("ABC-123", "prompt"))

    @patch("builtins.input")
    def test_missing_open_billing_account_stops_without_prompt(self, input_mock):
        self.assertEqual(_select_billing_account_interactive([]), ("", ""))
        input_mock.assert_not_called()

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

    @patch("builtins.input", return_value="")
    def test_blank_replacement_stops_when_allowed(self, _input):
        selected, source = _select_gcp_project_interactive(
            [{"id": "a-project", "name": "Alpha"}],
            allow_blank=True,
        )

        self.assertEqual((selected, source), ("", ""))

    @patch("builtins.input", return_value="1")
    def test_single_replacement_project_requires_selection(self, _input):
        selected, source = _select_gcp_project_interactive(
            [{"id": "a-project", "name": "Alpha"}],
            allow_blank=True,
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


class GcpZoneSelectionTest(TestCase):
    @patch("hyops.init.targets.gcp.run_capture")
    def test_discovers_up_zones_in_selected_region(self, run_capture):
        run_capture.return_value = SimpleNamespace(
            rc=0,
            stdout=(
                "europe-west2-a europe-west2 UP\n"
                "europe-west2-b europe-west2 DOWN\n"
                "europe-west2-c europe-west2 UP\n"
                "europe-west1-b europe-west1 UP\n"
            ),
        )

        zones = _discover_gcp_zones(
            project_id="demo-project",
            region="europe-west2",
            evidence_dir=Path("/tmp/evidence"),
        )

        self.assertEqual(zones, ["europe-west2-a", "europe-west2-c"])

    @patch("builtins.input", return_value="2")
    def test_selects_zone_by_number(self, _input):
        selected = _select_gcp_zone_interactive(
            ["europe-west2-a", "europe-west2-b"],
            region="europe-west2",
        )

        self.assertEqual(selected, "europe-west2-b")

    @patch("builtins.input", return_value="")
    def test_keeps_existing_zone(self, _input):
        selected = _select_gcp_zone_interactive(
            ["europe-west2-a", "europe-west2-b"],
            region="europe-west2",
            default="europe-west2-b",
        )

        self.assertEqual(selected, "europe-west2-b")


class GcpDefaultsReviewTest(TestCase):
    @patch("hyops.init.targets.gcp._prompt_gcp_region", return_value="europe-west2")
    @patch("builtins.input", return_value="")
    def test_does_not_prompt_for_unneeded_billing_account(self, input_mock, _region):
        values = _review_detected_gcp_defaults_interactive(
            env_name="academic-demo",
            project_id="existing-project",
            project_id_source="gcloud",
            region="europe-west2",
            region_source="gcloud",
            billing_account_id="",
            billing_account_source="",
        )

        self.assertEqual(values, ("existing-project", "europe-west2", ""))
        input_mock.assert_called_once_with("GCP project id [existing-project]: ")


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
