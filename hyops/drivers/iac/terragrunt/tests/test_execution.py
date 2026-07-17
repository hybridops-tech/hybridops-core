from unittest import TestCase

from hyops.drivers.iac.terragrunt._internal.execution import translate_gcp_capacity_error


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

        self.assertIn("temporarily unavailable in europe-west2-a", message)
        self.assertIn("for n2-standard-8", message)
        self.assertIn("The requested VM was not created.", message)
        self.assertIn("hyops init gcp --env demo-lab --force", message)
        self.assertIn("choose a different compute location", message)

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
