"""Tests for the complete GCP EVE-NG teaching blueprint."""

from pathlib import Path
from unittest import TestCase

from hyops.blueprint.schema import load_blueprint, validate_blueprint


class GcpEveNgBlueprintTest(TestCase):
    def test_declares_complete_local_state_lab(self):
        root = Path(__file__).resolve().parents[3]
        path = root / "blueprints" / "gcp" / "eve-ng@v1" / "blueprint.yml"
        validated = validate_blueprint(load_blueprint(path), path)

        self.assertTrue(validated["access"]["offer_destroy_on_close"])

        self.assertEqual(
            validated["order"],
            [
                "gcp_eve_ng_network",
                "gcp_eve_ng_vm",
                "gcp_eve_ng_config",
                "gcp_eve_ng_images",
                "gcp_eve_ng_healthcheck",
            ],
        )
        by_id = {step["id"]: step for step in validated["steps"]}
        self.assertEqual(
            by_id["gcp_eve_ng_network"]["execution_profile"],
            "gcp-local@v1.0",
        )
        self.assertEqual(
            by_id["gcp_eve_ng_vm"]["execution_profile"],
            "gcp-local@v1.0",
        )
        self.assertTrue(by_id["gcp_eve_ng_vm"]["inputs"]["zone_from_init_region"])
        self.assertTrue(
            by_id["gcp_eve_ng_config"]["inputs"]["eveng_guest_nat_enabled"]
        )
        self.assertEqual(
            len(by_id["gcp_eve_ng_images"]["inputs"]["eveng_images_list"]), 4
        )
        self.assertEqual(
            by_id["gcp_eve_ng_healthcheck"]["requires"], ["gcp_eve_ng_images"]
        )
