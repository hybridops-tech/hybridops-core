"""Tests for the standalone Proxmox EVE-NG blueprint."""

from pathlib import Path
from unittest import TestCase

from hyops.blueprint.schema import load_blueprint, validate_blueprint


class OnPremEveNgBlueprintTest(TestCase):
    def test_standalone_lab_does_not_require_netbox(self):
        root = Path(__file__).resolve().parents[3]
        path = root / "blueprints" / "onprem" / "eve-ng@v1" / "blueprint.yml"
        payload = load_blueprint(path)
        validated = validate_blueprint(payload, path)

        self.assertEqual(validated["policy"]["ipam_authority"], "none")
        self.assertTrue(validated["access"]["offer_destroy_on_close"])
        self.assertEqual(
            validated["archive_before_destroy"]["module_ref"],
            "platform/linux/eve-ng-lab-archive",
        )
        self.assertEqual(len(validated["steps"]), 5)
        vm_step = next(
            step for step in validated["steps"] if step["id"] == "eve_ng_vm"
        )
        self.assertEqual(vm_step["contracts"]["addressing_mode"], "static")
        self.assertEqual(vm_step["contracts"]["requires_authority"], "none")
        self.assertFalse(vm_step["inputs"]["require_ipam"])
        interface = vm_step["inputs"]["vms"]["eve-ng-01"]["interfaces"][0]
        self.assertEqual(interface["bridge"], "vmbr0")
        self.assertEqual(interface["ipv4"]["address"], "dhcp")

        config_step = next(
            step for step in validated["steps"] if step["id"] == "eve_ng_config"
        )
        self.assertTrue(config_step["inputs"]["eveng_guest_nat_enabled"])
        health_step = next(
            step for step in validated["steps"] if step["id"] == "eve_ng_healthcheck"
        )
        self.assertEqual(health_step["requires"], ["eve_ng_images"])
