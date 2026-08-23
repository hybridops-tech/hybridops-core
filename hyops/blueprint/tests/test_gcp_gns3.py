from pathlib import Path
from unittest import TestCase

from hyops.blueprint.schema import load_blueprint, validate_blueprint


class GCPGNS3BlueprintTest(TestCase):
    def setUp(self) -> None:
        root = Path(__file__).resolve().parents[3]
        path = root / "blueprints" / "gcp" / "gns3@v1" / "blueprint.yml"
        self.blueprint = validate_blueprint(load_blueprint(path), path)

    def test_private_six_stage_chain(self) -> None:
        self.assertEqual(
            [step["id"] for step in self.blueprint["steps"]],
            [
                "gcp_gns3_network",
                "gcp_gns3_vm",
                "gcp_gns3_server",
                "gcp_gns3_images",
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

    def test_guest_operations_are_destroyed_with_disposable_vm(self) -> None:
        for step in self.blueprint["steps"][2:]:
            self.assertEqual(step["destroy_subsumed_by"], "gcp_gns3_vm")

    def test_access_uses_loopback_iap_forward(self) -> None:
        access = self.blueprint["access"]
        self.assertEqual(access["type"], "gcp-iap-ssh-forward")
        self.assertEqual(access["remote_port"], 3080)
        self.assertEqual(access["local_port"], 3080)
        self.assertEqual(access["native_console_mode"], "gns3-api")
        self.assertEqual(access["native_console_username"], "gns3")
        self.assertEqual(
            access["native_console_password_env"],
            "GNS3_SERVER_PASSWORD",
        )
        self.assertTrue(access["offer_destroy_on_close"])
        self.assertFalse(access["open_browser"])
        self.assertEqual(
            access["automation"]["management_cidr"],
            "172.29.130.0/24",
        )
        self.assertEqual(
            access["automation"]["management_network_label"],
            "hyops-mgmt0",
        )

    def test_required_health_stage_is_deep(self) -> None:
        health = self.blueprint["steps"][5]
        self.assertEqual(health["requires"], ["gcp_gns3_starter_lab"])
        self.assertTrue(health["inputs"]["gns3_healthcheck_deep"])

    def test_server_builds_private_management_bridge(self) -> None:
        server = self.blueprint["steps"][2]
        self.assertTrue(server["inputs"]["gns3_server_management_access_enabled"])

    def test_destroy_protects_gns3_project_state(self) -> None:
        archive = self.blueprint["archive_before_destroy"]
        self.assertEqual(
            archive["module_ref"],
            "platform/linux/gns3-lab-archive",
        )
        self.assertEqual(archive["contract_prefix"], "gns3_lab_archive")
        self.assertFalse(archive["node_state"])
        self.assertTrue(archive["restore_overwrite_default"])
        self.assertFalse(archive["inputs"]["gns3_lab_archive_include_images"])

    def test_images_are_verified_before_starter_lab(self) -> None:
        image_step = self.blueprint["steps"][3]
        self.assertEqual(image_step["requires"], ["gcp_gns3_server"])
        image = image_step["inputs"]["gns3_images_items"][0]
        self.assertEqual(image["disk_type"], "cdrom")
        self.assertRegex(image["checksum"], r"^sha256:[0-9a-f]{64}$")
