from pathlib import Path
from unittest import TestCase

from hyops.blueprint.schema import load_blueprint, validate_blueprint


class GCPGNS3BlueprintTest(TestCase):
    def setUp(self) -> None:
        root = Path(__file__).resolve().parents[3]
        path = root / "blueprints" / "gcp" / "gns3@v1" / "blueprint.yml"
        self.blueprint = validate_blueprint(load_blueprint(path), path)

    def test_private_five_stage_chain(self) -> None:
        self.assertEqual(
            [step["id"] for step in self.blueprint["steps"]],
            [
                "gcp_gns3_network",
                "gcp_gns3_vm",
                "gcp_gns3_server",
                "gcp_gns3_starter_lab",
                "gcp_gns3_healthcheck",
            ],
        )
        vm_inputs = self.blueprint["steps"][1]["inputs"]
        self.assertFalse(vm_inputs["assign_public_ip"])
        self.assertTrue(vm_inputs["enable_nested_virtualization"])

    def test_operations_use_iap(self) -> None:
        for step in self.blueprint["steps"][2:]:
            self.assertEqual(step["inputs"]["ssh_access_mode"], "gcp-iap")

    def test_access_uses_loopback_iap_forward(self) -> None:
        access = self.blueprint["access"]
        self.assertEqual(access["type"], "gcp-iap-ssh-forward")
        self.assertEqual(access["remote_port"], 3080)
        self.assertEqual(access["local_port"], 3080)
        self.assertFalse(access["open_browser"])

    def test_required_health_stage_is_deep(self) -> None:
        health = self.blueprint["steps"][4]
        self.assertEqual(health["requires"], ["gcp_gns3_starter_lab"])
        self.assertTrue(health["inputs"]["gns3_healthcheck_deep"])
