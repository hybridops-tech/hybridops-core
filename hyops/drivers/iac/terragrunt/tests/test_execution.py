from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch

from hyops.drivers.iac.terragrunt._internal.execution import (
    run_terragrunt_operation,
    translate_gcp_capacity_error,
)
from hyops.runtime.proc import ProcResult


class GcpCapacityErrorTest(TestCase):
    def test_translates_zonal_capacity_failure(self):
        stderr = (
            "The zone 'projects/student-project/zones/europe-west2-a' does not "
            "have enough resources available to fulfill the request.\n"
            "A n2-standard-8 VM instance is currently unavailable in the "
            "europe-west2-a zone."
        )

        message = translate_gcp_capacity_error(
            command_name="apply",
            stdout="",
            stderr=stderr,
            env={"HYOPS_ENV": "demo-lab"},
        )

        self.assertIn("GCP capacity unavailable: n2-standard-8 in europe-west2-a", message)
        self.assertIn("VM not created", message)
        self.assertIn(
            "hyops init gcp --env demo-lab --with-cli-login --force",
            message,
        )
        self.assertIn("choose another zone", message)

    def test_ignores_unrelated_provider_failure(self):
        message = translate_gcp_capacity_error(
            command_name="apply",
            stdout="",
            stderr="Permission denied while creating the instance.",
            env={"HYOPS_ENV": "demo-lab"},
        )

        self.assertEqual(message, "")

    def test_ignores_capacity_text_during_destroy(self):
        message = translate_gcp_capacity_error(
            command_name="destroy",
            stdout="",
            stderr="ZONE_RESOURCE_POOL_EXHAUSTED",
            env={"HYOPS_ENV": "demo-lab"},
        )

        self.assertEqual(message, "")

    def test_translates_capacity_failure_from_streamed_evidence(self):
        with TemporaryDirectory() as tmp:
            evidence_dir = Path(tmp)
            (evidence_dir / "terragrunt_apply.stdout.txt").write_text("", encoding="utf-8")
            (evidence_dir / "terragrunt_apply.stderr.txt").write_text(
                "The zone 'projects/student-project/zones/europe-west2-a' does not "
                "have enough resources available to fulfill the request.\n"
                "A n2-standard-8 VM instance is currently unavailable in the "
                "europe-west2-a zone.\n",
                encoding="utf-8",
            )
            streamed_result = ProcResult(
                argv=["terragrunt", "apply"],
                cwd=tmp,
                rc=1,
                duration_ms=10,
                stdout="",
                stderr="",
            )

            with patch(
                "hyops.drivers.iac.terragrunt._internal.execution.run_capture_with_policy",
                return_value=streamed_result,
            ):
                outputs, error = run_terragrunt_operation(
                    command_name="apply",
                    request={},
                    tg_bin="terragrunt",
                    apply_args=["apply"],
                    destroy_args=["destroy"],
                    import_args=["import"],
                    force_unlock_args=["force-unlock"],
                    plan_args=["plan"],
                    validate_args=["validate"],
                    output_args=["output"],
                    stack_dst=evidence_dir,
                    env={"HYOPS_ENV": "demo-lab"},
                    evidence_dir=evidence_dir,
                    policy_timeout_s=None,
                    policy_redact=True,
                    policy_retries=0,
                    tg_log=evidence_dir / "terragrunt.log",
                )

        self.assertEqual(outputs, {})
        self.assertIn("GCP capacity unavailable: n2-standard-8 in europe-west2-a", error)
