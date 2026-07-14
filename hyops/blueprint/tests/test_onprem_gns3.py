"""Tests for the standalone Proxmox GNS3 blueprint."""

from pathlib import Path
from unittest import TestCase

from hyops.blueprint.schema import load_blueprint, validate_blueprint


class OnPremGNS3BlueprintTest(TestCase):
    def setUp(self) -> None:
        root = Path(__file__).resolve().parents[3]
        self.path = root / "blueprints" / "onprem" / "gns3@v1" / "blueprint.yml"
        self.blueprint = validate_blueprint(load_blueprint(self.path), self.path)

    def test_blueprint_uses_standalone_proxmox_path(self) -> None:
        self.assertEqual(self.blueprint["policy"]["ipam_authority"], "none")
        self.assertEqual(
            [step["id"] for step in self.blueprint["steps"]],
            [
                "template_image_jammy",
                "gns3_vm",
                "gns3_server",
                "gns3_images",
                "gns3_starter_lab",
                "gns3_healthcheck",
            ],
        )

        vm_step = self.blueprint["steps"][1]
        self.assertFalse(vm_step["inputs"]["require_ipam"])
        self.assertEqual(vm_step["inputs"]["cpu_type"], "host")
        interface = vm_step["inputs"]["vms"]["gns3-01"]["interfaces"][0]
        self.assertEqual(interface["bridge"], "vmbr0")
        self.assertEqual(interface["ipv4"]["address"], "dhcp")

    def test_server_requires_nested_kvm_and_private_api(self) -> None:
        server_step = self.blueprint["steps"][2]
        self.assertEqual(server_step["requires"], ["gns3_vm"])
        self.assertEqual(
            server_step["inputs"]["inventory_state_ref"],
            "platform/onprem/platform-vm#gns3_vm",
        )
        self.assertEqual(server_step["inputs"]["gns3_server_bind_address"], "127.0.0.1")
        self.assertEqual(server_step["inputs"]["gns3_server_port"], 3080)
        self.assertTrue(server_step["inputs"]["gns3_server_require_kvm"])

    def test_desktop_client_access_uses_private_tcp_forward(self) -> None:
        access = self.blueprint["access"]
        self.assertEqual(access["type"], "ssh-tcp-forward")
        self.assertEqual(access["state_ref"], "platform/onprem/platform-vm#gns3_vm")
        self.assertEqual(access["remote_port"], 3080)
        self.assertEqual(access["local_port"], 3080)

    def test_template_is_retained_during_blueprint_destroy(self) -> None:
        template_step = self.blueprint["steps"][0]
        self.assertTrue(template_step["retain_on_destroy"])
        self.assertEqual(
            template_step["inputs"]["template_key"],
            "ubuntu-22.04",
        )

    def test_healthcheck_runs_disposable_vpcs_lifecycle(self) -> None:
        health_step = self.blueprint["steps"][5]
        self.assertEqual(health_step["requires"], ["gns3_starter_lab"])
        self.assertEqual(
            health_step["module_ref"], "platform/linux/gns3-healthcheck"
        )
        self.assertTrue(health_step["inputs"]["gns3_healthcheck_deep"])

    def test_starter_lab_uses_builtin_topology(self) -> None:
        starter_step = self.blueprint["steps"][4]
        self.assertEqual(starter_step["requires"], ["gns3_images"])
        self.assertEqual(
            starter_step["module_ref"], "platform/linux/gns3-starter-lab"
        )
        self.assertEqual(
            starter_step["inputs"]["gns3_starter_lab_project_name"],
            "HybridOps Starter Lab",
        )

    def test_images_are_verified_before_starter_lab(self) -> None:
        image_step = self.blueprint["steps"][3]
        self.assertEqual(image_step["requires"], ["gns3_server"])
        image = image_step["inputs"]["gns3_images_items"][0]
        self.assertEqual(image["disk_type"], "cdrom")
        self.assertRegex(image["checksum"], r"^sha256:[0-9a-f]{64}$")
