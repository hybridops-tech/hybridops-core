from pathlib import Path
from unittest import TestCase

from hyops.blueprint.schema import load_blueprint, validate_blueprint


class AzureRecoveryNetworkFoundationBlueprintTests(TestCase):
    def setUp(self) -> None:
        path = (
            Path(__file__).resolve().parents[3]
            / "blueprints"
            / "azure"
            / "recovery-network-foundation@v1"
            / "blueprint.yml"
        )
        self.blueprint = validate_blueprint(load_blueprint(path), path)

    def test_orders_resource_boundary_before_network(self) -> None:
        self.assertEqual(
            self.blueprint["blueprint_ref"],
            "azure/recovery-network-foundation@v1",
        )
        self.assertEqual(
            self.blueprint["order"],
            ["recovery_resource_group", "recovery_network"],
        )

    def test_declares_consistent_recovery_network_target(self) -> None:
        by_id = {step["id"]: step for step in self.blueprint["steps"]}
        resource_group = by_id["recovery_resource_group"]
        network = by_id["recovery_network"]

        self.assertEqual(
            resource_group["inputs"]["resource_group_name"],
            "rg-hybridops-recovery",
        )
        self.assertEqual(resource_group["inputs"]["location"], "uksouth")
        self.assertEqual(
            network["inputs"]["vnet_name"],
            "vnet-hybridops-recovery",
        )
        self.assertEqual(
            network["inputs"]["resource_group_name"],
            "rg-hybridops-recovery",
        )
        self.assertEqual(network["inputs"]["location"], "uksouth")
        self.assertEqual(network["inputs"]["address_space"], ["10.84.0.0/16"])
        self.assertEqual(resource_group["inputs"]["context_id"], "recovery")
        self.assertEqual(network["inputs"]["context_id"], "recovery")
        self.assertEqual(
            resource_group["inputs"]["resource_group_name"],
            network["inputs"]["resource_group_name"],
        )
        self.assertEqual(
            resource_group["inputs"]["location"],
            network["inputs"]["location"],
        )
        self.assertEqual(network["requires"], ["recovery_resource_group"])
        self.assertTrue(self.blueprint["policy"]["evidence_required"])

    def test_shipped_contract_has_no_demonstration_identity(self) -> None:
        contract_text = str(self.blueprint).lower()
        self.assertNotIn("agentic", contract_text)
        self.assertNotIn("disposable", contract_text)

