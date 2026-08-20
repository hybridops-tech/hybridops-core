from pathlib import Path
from unittest import TestCase

from hyops.blueprint.schema import load_blueprint, validate_blueprint


class GCPContainerlabBlueprintTest(TestCase):
    def setUp(self) -> None:
        root = Path(__file__).resolve().parents[3]
        path = root / "blueprints" / "gcp" / "containerlab@v1" / "blueprint.yml"
        self.blueprint = validate_blueprint(load_blueprint(path), path)

    def test_private_six_stage_chain(self) -> None:
        self.assertEqual(
            [step["id"] for step in self.blueprint["steps"]],
            [
                "gcp_containerlab_network",
                "gcp_containerlab_vm",
                "gcp_containerlab_runtime",
                "gcp_containerlab_lab",
                "gcp_containerlab_healthcheck",
                "gcp_containerlab_recovery_guard",
            ],
        )
        vm_inputs = self.blueprint["steps"][1]["inputs"]
        self.assertFalse(vm_inputs["assign_public_ip"])
        self.assertTrue(vm_inputs["enable_nested_virtualization"])
        self.assertEqual(vm_inputs["machine_type"], "n2-highmem-8")

    def test_operations_use_iap(self) -> None:
        for step in self.blueprint["steps"][2:]:
            self.assertEqual(step["inputs"]["ssh_access_mode"], "gcp-iap")

    def test_containerlab_remains_native_topology_boundary(self) -> None:
        lab_step = self.blueprint["steps"][3]
        lab = lab_step["inputs"]
        self.assertEqual(lab_step["action"], "deploy")
        self.assertEqual(lab["containerlab_lab_topology_relpath"], "lab.clab.yml")
        self.assertEqual(lab["containerlab_lab_required_images"], [])
        self.assertFalse(lab["containerlab_lab_pull_missing_images"])
        self.assertTrue(lab["containerlab_lab_restore_latest"])

    def test_source_tree_is_separate_from_native_generated_labdir(self) -> None:
        lab = self.blueprint["steps"][3]["inputs"]
        health = self.blueprint["steps"][4]["inputs"]
        recovery = self.blueprint["steps"][5]["inputs"]

        source_root = lab["containerlab_lab_remote_dir"]
        labdir_base = lab["containerlab_lab_labdir_base"]
        self.assertNotEqual(source_root.rstrip("/"), labdir_base.rstrip("/"))
        self.assertEqual(
            labdir_base,
            "/var/lib/hybridops/containerlab/labdirs",
        )
        self.assertEqual(
            health["containerlab_healthcheck_labdir_base"],
            labdir_base,
        )
        self.assertEqual(
            recovery["containerlab_recovery_labdir_base"],
            labdir_base,
        )

    def test_recovery_guard_is_last_and_automatic(self) -> None:
        self.assertFalse(self.blueprint["archive_before_destroy"])
        recovery = self.blueprint["steps"][5]
        inputs = recovery["inputs"]
        self.assertEqual(recovery["requires"], ["gcp_containerlab_healthcheck"])
        self.assertEqual(inputs["containerlab_recovery_action"], "arm")
        self.assertEqual(inputs["containerlab_recovery_mode"], "rebuild")
        self.assertEqual(
            inputs["containerlab_recovery_source_root"],
            "/var/lib/hybridops/containerlab/labs/gcp-containerlab",
        )
        self.assertFalse(inputs["containerlab_recovery_include_lab_dir"])

    def test_runtime_and_recovery_require_kvm_capable_host(self) -> None:
        runtime = self.blueprint["steps"][2]["inputs"]
        health = self.blueprint["steps"][4]["inputs"]
        self.assertEqual(runtime["containerlab_version"], "0.78.0")
        self.assertEqual(runtime["containerlab_package_checksum"], "")
        self.assertTrue(runtime["containerlab_require_kvm"])
        self.assertEqual(health["containerlab_healthcheck_expected_version"], "0.78.0")
        self.assertTrue(health["containerlab_healthcheck_require_kvm"])

    def test_access_is_private_ssh_endpoint_with_destroy_offer(self) -> None:
        access = self.blueprint["access"]
        self.assertEqual(access["type"], "gcp-iap-ssh-forward")
        self.assertEqual(access["remote_port"], 22)
        self.assertFalse(access["open_browser"])
        self.assertTrue(access["offer_destroy_on_close"])
