from pathlib import Path
from unittest import TestCase

from hyops.blueprint.schema import load_blueprint, validate_blueprint


class LinuxContainerlabBlueprintTest(TestCase):
    def setUp(self) -> None:
        root = Path(__file__).resolve().parents[3]
        self.path = root / "blueprints" / "linux" / "containerlab@v1" / "blueprint.yml"
        self.blueprint = validate_blueprint(load_blueprint(self.path), self.path)

    def test_local_five_stage_chain(self) -> None:
        self.assertEqual(
            [step["id"] for step in self.blueprint["steps"]],
            [
                "local_containerlab_runtime",
                "local_containerlab_lab",
                "local_containerlab_gui",
                "local_containerlab_healthcheck",
                "local_containerlab_recovery_guard",
            ],
        )

    def test_all_steps_use_local_execution(self) -> None:
        for step in self.blueprint["steps"]:
            self.assertEqual(step["inputs"]["target_host"], "127.0.0.1")
            self.assertTrue(step["inputs"]["local_execution"])
            self.assertFalse(step["inputs"]["connectivity_check"])

    def test_runtime_is_retained_and_recovery_is_gated(self) -> None:
        runtime = self.blueprint["steps"][0]
        recovery = self.blueprint["steps"][-1]
        self.assertTrue(runtime["retain_on_destroy"])
        self.assertFalse(
            self.blueprint["steps"][1]["inputs"]["containerlab_lab_destroy_all"]
        )
        self.assertFalse(runtime["inputs"]["containerlab_require_kvm"])
        self.assertFalse(
            self.blueprint["steps"][3]["inputs"][
                "containerlab_healthcheck_require_kvm"
            ]
        )
        self.assertTrue(recovery["destroy_gate"])
        self.assertIn("local_containerlab_lab", recovery["requires"])
        self.assertTrue(
            recovery["inputs"]["containerlab_recovery_include_lab_dir"]
        )

    def test_gui_and_direct_automation_access_are_local(self) -> None:
        access = self.blueprint["access"]
        self.assertEqual(access["type"], "linux-host-http")
        self.assertEqual(access["host"], "127.0.0.1")
        self.assertEqual(access["scheme"], "https")
        self.assertEqual(access["remote_port"], 3001)
        self.assertEqual(
            access["automation"]["discovery_mode"],
            "containerlab-inspect",
        )
        self.assertEqual(
            access["automation"]["discovery_topology_path"],
            "/var/lib/hybridops/containerlab/labs/${USER}/local-containerlab/lab.clab.yml",
        )

    def test_gui_workspace_contains_the_managed_topology(self) -> None:
        lab = self.blueprint["steps"][1]["inputs"]
        gui = self.blueprint["steps"][2]["inputs"]
        self.assertEqual(lab["containerlab_lab_remote_owner"], "${USER}")
        self.assertTrue(
            lab["containerlab_lab_remote_dir"].startswith(
                gui["containerlab_gui_labs_dir"] + "/${USER}/"
            )
        )

    def test_local_access_rejects_a_remote_host(self) -> None:
        spec = load_blueprint(self.path)
        spec["access"]["host"] = "192.0.2.20"
        with self.assertRaisesRegex(ValueError, "must be loopback"):
            validate_blueprint(spec, self.path)

    def test_containerlab_discovery_path_must_be_absolute(self) -> None:
        spec = load_blueprint(self.path)
        spec["access"]["automation"]["discovery_topology_path"] = "lab.clab.yml"
        with self.assertRaisesRegex(ValueError, "must be an absolute path"):
            validate_blueprint(spec, self.path)

    def test_containerlab_discovery_path_rejects_parent_traversal(self) -> None:
        spec = load_blueprint(self.path)
        spec["access"]["automation"]["discovery_topology_path"] = (
            "/var/lib/hybridops/../lab.clab.yml"
        )
        with self.assertRaisesRegex(ValueError, "must not traverse"):
            validate_blueprint(spec, self.path)
