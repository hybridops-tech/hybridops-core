from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import Mock, patch

from hyops.drivers.iac.terragrunt._internal.preflight import (
    _gcp_vm_name,
    _preflight_gcp_vm_cpu_quota,
    run_preflight_phase,
)


def _inputs(*, machine_type: str = "n2-standard-8") -> dict:
    return {
        "project_id": "student-project",
        "name_prefix": "platform",
        "context_id": "labs",
        "zone": "europe-west2-a",
        "machine_type": machine_type,
        "vms": {"eve-ng-01": {"role": "eve-ng"}},
    }


def _gcloud_response(
    *,
    instances: list[dict],
    limit: float = 12,
    usage: float = 8,
    shapes: dict[str, int] | None = None,
):
    shape_cpus = shapes or {"n2-standard-8": 8, "n2-standard-4": 4}

    def response(args, *, env):
        del env
        if args[:3] == ["compute", "instances", "list"]:
            return instances, ""
        if args[:3] == ["compute", "project-info", "describe"]:
            return {
                "quotas": [
                    {
                        "metric": "CPUS_ALL_REGIONS",
                        "limit": limit,
                        "usage": usage,
                    }
                ]
            }, ""
        if args[:3] == ["compute", "machine-types", "describe"]:
            machine_type = args[3]
            return {"guestCpus": shape_cpus[machine_type]}, ""
        raise AssertionError(f"unexpected gcloud request: {args}")

    return response


class GcpVmCpuQuotaPreflightTest(TestCase):
    def _run(self, inputs: dict) -> tuple[str, dict]:
        return _preflight_gcp_vm_cpu_quota(
            lifecycle_command="deploy",
            module_ref="platform/gcp/platform-vm",
            profile_ref="gcp-local@v1.0",
            runtime={},
            inputs=inputs,
            env={"HYOPS_ENV": "demo-lab2"},
        )

    def test_vm_name_matches_terraform_normalization(self):
        self.assertEqual(
            _gcp_vm_name("platform", "gns3-lab", "gns3-01"),
            "platform-gns3-lab-gns3-01",
        )

    @patch("hyops.drivers.iac.terragrunt._internal.preflight._gcloud_json")
    def test_blocks_when_existing_vm_consumes_global_quota(self, gcloud_json):
        gcloud_json.side_effect = _gcloud_response(
            instances=[
                {
                    "name": "platform-gns3-lab-gns3-01",
                    "zone": "zones/europe-west2-a",
                    "machineType": "machineTypes/n2-standard-8",
                    "status": "RUNNING",
                    "labels": {"role": "gns3", "workload": "network-lab"},
                }
            ]
        )

        error, summary = self._run(_inputs())

        self.assertIn("metric=CPUS_ALL_REGIONS", error)
        self.assertIn("limit=12", error)
        self.assertIn("used=8", error)
        self.assertIn("available=4", error)
        self.assertIn("planned_additional=8", error)
        self.assertIn("shortfall=4", error)
        self.assertIn("platform-gns3-lab-gns3-01", error)
        self.assertIn("role=gns3", error)
        self.assertIn("No resources were changed", error)
        self.assertEqual(summary["shortfall"], 4)
        self.assertEqual(summary["active_instances"][0]["role"], "gns3")

    @patch("hyops.drivers.iac.terragrunt._internal.preflight._gcloud_json")
    def test_allows_request_that_fits_remaining_global_quota(self, gcloud_json):
        gcloud_json.side_effect = _gcloud_response(
            instances=[
                {
                    "name": "platform-gns3-lab-gns3-01",
                    "zone": "zones/europe-west2-a",
                    "machineType": "machineTypes/n2-standard-8",
                    "status": "RUNNING",
                }
            ],
            limit=16,
            usage=8,
        )

        error, summary = self._run(_inputs())

        self.assertEqual(error, "")
        self.assertEqual(summary["planned_additional"], 8)
        self.assertEqual(summary["shortfall"], 0)

    @patch("hyops.drivers.iac.terragrunt._internal.preflight._gcloud_json")
    def test_does_not_double_count_existing_planned_vm(self, gcloud_json):
        gcloud_json.side_effect = _gcloud_response(
            instances=[
                {
                    "name": "platform-labs-eve-ng-01",
                    "zone": "zones/europe-west2-a",
                    "machineType": "machineTypes/n2-standard-8",
                    "status": "RUNNING",
                }
            ],
            limit=12,
            usage=8,
        )

        error, summary = self._run(_inputs())

        self.assertEqual(error, "")
        self.assertEqual(summary["planned_additional"], 0)
        self.assertEqual(summary["available"], 4)

    @patch("hyops.drivers.iac.terragrunt._internal.preflight._gcloud_json")
    def test_counts_only_resize_increase_for_existing_vm(self, gcloud_json):
        gcloud_json.side_effect = _gcloud_response(
            instances=[
                {
                    "name": "platform-labs-eve-ng-01",
                    "zone": "zones/europe-west2-a",
                    "machineType": "machineTypes/n2-standard-4",
                    "status": "RUNNING",
                }
            ],
            limit=6,
            usage=4,
        )

        error, summary = self._run(_inputs(machine_type="n2-standard-8"))

        self.assertIn("planned_additional=4", error)
        self.assertIn("shortfall=2", error)
        self.assertEqual(summary["shortfall"], 2)

    @patch("hyops.drivers.iac.terragrunt._internal.preflight._gcloud_json")
    def test_same_name_in_another_zone_is_not_treated_as_planned_vm(self, gcloud_json):
        gcloud_json.side_effect = _gcloud_response(
            instances=[
                {
                    "name": "platform-labs-eve-ng-01",
                    "zone": "zones/europe-west2-b",
                    "machineType": "machineTypes/n2-standard-8",
                    "status": "RUNNING",
                }
            ],
            limit=12,
            usage=8,
        )

        error, summary = self._run(_inputs())

        self.assertIn("planned_additional=8", error)
        self.assertEqual(summary["shortfall"], 4)

    @patch("hyops.drivers.iac.terragrunt._internal.preflight._gcloud_json")
    def test_fails_closed_when_global_quota_is_missing(self, gcloud_json):
        def response(args, *, env):
            del env
            if args[:3] == ["compute", "instances", "list"]:
                return [], ""
            if args[:3] == ["compute", "project-info", "describe"]:
                return {"quotas": []}, ""
            raise AssertionError(f"unexpected gcloud request: {args}")

        gcloud_json.side_effect = response

        error, summary = self._run(_inputs())

        self.assertIn("did not return a valid CPUS_ALL_REGIONS quota", error)
        self.assertEqual(summary, {})

    @patch("hyops.drivers.iac.terragrunt._internal.preflight._gcloud_json")
    def test_destroy_skips_quota_calls(self, gcloud_json):
        error, summary = _preflight_gcp_vm_cpu_quota(
            lifecycle_command="destroy",
            module_ref="platform/gcp/platform-vm",
            profile_ref="gcp-local@v1.0",
            runtime={},
            inputs=_inputs(),
            env={},
        )

        self.assertEqual((error, summary), ("", {}))
        gcloud_json.assert_not_called()


class GcpVmCpuQuotaPreflightIntegrationTest(TestCase):
    @patch(
        "hyops.drivers.iac.terragrunt._internal.preflight._preflight_gcp_vm_cpu_quota",
        return_value=("", {"metric": "CPUS_ALL_REGIONS", "shortfall": 0}),
    )
    @patch(
        "hyops.drivers.iac.terragrunt._internal.preflight._preflight_gcp_billing",
        return_value="",
    )
    def test_success_preserves_structured_quota_summary(self, _billing, quota):
        with TemporaryDirectory() as tmp:
            result = {"status": "error", "normalized_outputs": {}, "warnings": []}
            handled, error = run_preflight_phase(
                command_name="preflight",
                result=result,
                policy_defaults={"min_free_disk_mb": 0},
                runtime_root=Path(tmp),
                backend_mode="local",
                env={},
                env_name="demo-lab2",
                export_infra_hook=None,
                contract=Mock(),
                module_ref="platform/gcp/platform-vm",
                runtime={"lifecycle_command": "deploy"},
                profile_ref="gcp-local@v1.0",
                pack_id="gcp/platform-vm",
                required_credentials=["gcp"],
                inputs=_inputs(),
            )

        self.assertTrue(handled)
        self.assertEqual(error, "")
        self.assertEqual(result["status"], "ok")
        self.assertEqual(
            result["normalized_outputs"]["preflight"]["gcp_cpu_quota"]["metric"],
            "CPUS_ALL_REGIONS",
        )
        quota.assert_called_once()

    @patch(
        "hyops.drivers.iac.terragrunt._internal.preflight._preflight_gcp_vm_cpu_quota",
        return_value=(
            "quota shortage",
            {"metric": "CPUS_ALL_REGIONS", "shortfall": 4},
        ),
    )
    @patch(
        "hyops.drivers.iac.terragrunt._internal.preflight._preflight_gcp_billing",
        return_value="",
    )
    def test_failure_keeps_quota_summary_for_run_record(self, _billing, _quota):
        with TemporaryDirectory() as tmp:
            result = {"status": "error", "normalized_outputs": {}, "warnings": []}
            handled, error = run_preflight_phase(
                command_name="preflight",
                result=result,
                policy_defaults={"min_free_disk_mb": 0},
                runtime_root=Path(tmp),
                backend_mode="local",
                env={},
                env_name="demo-lab2",
                export_infra_hook=None,
                contract=Mock(),
                module_ref="platform/gcp/platform-vm",
                runtime={"lifecycle_command": "deploy"},
                profile_ref="gcp-local@v1.0",
                pack_id="gcp/platform-vm",
                required_credentials=["gcp"],
                inputs=_inputs(),
            )

        self.assertTrue(handled)
        self.assertEqual(error, "quota shortage")
        self.assertEqual(
            result["normalized_outputs"]["preflight"]["gcp_cpu_quota"]["shortfall"],
            4,
        )
