import json
import re
from pathlib import Path
from unittest import TestCase

import yaml


class ContainerlabModuleContractTest(TestCase):
    def setUp(self) -> None:
        self.root = Path(__file__).resolve().parents[2]

    def _spec(self, name: str) -> dict:
        path = self.root / "modules" / "platform" / "linux" / name / "spec.yml"
        return yaml.safe_load(path.read_text(encoding="utf-8"))

    def test_runtime_delegates_to_app_collection(self) -> None:
        spec = self._spec("containerlab")
        defaults = spec["inputs"]["defaults"]
        self.assertEqual(spec["execution"]["driver"], "config/ansible")
        self.assertEqual(defaults["containerlab_role_fqcn"], "hybridops.app.containerlab")
        self.assertEqual(defaults["containerlab_version"], "0.78.0")
        self.assertTrue(defaults["containerlab_require_kvm"])

    def test_healthcheck_tracks_same_pinned_runtime(self) -> None:
        spec = self._spec("containerlab-healthcheck")
        defaults = spec["inputs"]["defaults"]
        self.assertEqual(defaults["containerlab_healthcheck_expected_version"], "0.78.0")

    def test_native_labdir_contract_is_shared_and_separate_from_source(self) -> None:
        lab = self._spec("containerlab-lab")["inputs"]["defaults"]
        health = self._spec("containerlab-healthcheck")["inputs"]["defaults"]
        recovery = self._spec("containerlab-recovery")["inputs"]["defaults"]

        labdir_base = lab["containerlab_lab_labdir_base"]
        self.assertEqual(labdir_base, "/var/lib/hybridops/containerlab/labdirs")
        self.assertNotEqual(
            lab["containerlab_lab_remote_dir"].rstrip("/"),
            labdir_base.rstrip("/"),
        )
        self.assertEqual(health["containerlab_healthcheck_labdir_base"], labdir_base)
        self.assertEqual(recovery["containerlab_recovery_labdir_base"], labdir_base)

    def test_lab_keeps_native_source_and_restore_contract(self) -> None:
        spec = self._spec("containerlab-lab")
        defaults = spec["inputs"]["defaults"]
        self.assertEqual(defaults["containerlab_lab_topology_relpath"], "lab.clab.yml")
        self.assertEqual(defaults["containerlab_lab_required_images"], [])
        self.assertFalse(defaults["containerlab_lab_pull_missing_images"])
        self.assertFalse(defaults["containerlab_lab_restore_latest"])
        self.assertEqual(
            defaults["containerlab_lab_recovery_role_fqcn"],
            "hybridops.app.containerlab_recovery",
        )

    def test_recovery_publishes_destroy_gate(self) -> None:
        spec = self._spec("containerlab-recovery")
        outputs = set(spec["outputs"]["publish"])
        defaults = spec["inputs"]["defaults"]
        self.assertEqual(defaults["containerlab_recovery_action"], "arm")
        self.assertEqual(defaults["containerlab_recovery_mode"], "rebuild")
        self.assertIn("containerlab_recovery_latest_path", outputs)
        self.assertIn("containerlab_recovery_safe_for_host_destroy", outputs)
        self.assertIn("containerlab_recovery_labdir_base", outputs)
        self.assertFalse(defaults["containerlab_recovery_include_lab_dir"])

    def test_recovery_pack_has_destroy_gate_entrypoint(self) -> None:
        path = (
            self.root
            / "packs"
            / "config"
            / "ansible"
            / "linux"
            / "common"
            / "platform"
            / "63-containerlab-recovery@v1.0"
            / "stack"
            / "destroy.playbook.yml"
        )
        self.assertTrue(path.is_file())

    def test_destroy_wrappers_use_private_lifecycle_actions(self) -> None:
        stack_root = (
            self.root
            / "packs"
            / "config"
            / "ansible"
            / "linux"
            / "common"
            / "platform"
        )
        recovery_destroy = (
            stack_root
            / "63-containerlab-recovery@v1.0"
            / "stack"
            / "destroy.playbook.yml"
        ).read_text(encoding="utf-8")
        lab_destroy = (
            stack_root
            / "61-containerlab-lab@v1.0"
            / "stack"
            / "destroy.playbook.yml"
        ).read_text(encoding="utf-8")
        lab_apply = (
            stack_root
            / "61-containerlab-lab@v1.0"
            / "stack"
            / "playbook.yml"
        ).read_text(encoding="utf-8")

        self.assertIn("_containerlab_recovery_action: export", recovery_destroy)
        self.assertIn("_containerlab_recovery_topology_path:", recovery_destroy)
        self.assertIn("_containerlab_recovery_controller_dir:", recovery_destroy)
        self.assertNotIn("\n        containerlab_recovery_action: export", recovery_destroy)
        self.assertIn("_containerlab_lab_action: destroy", lab_destroy)
        self.assertIn("_containerlab_lab_destroy_all: true", lab_destroy)
        self.assertNotIn("\n            containerlab_lab_action: destroy", lab_destroy)
        self.assertIn("_containerlab_recovery_action: import", lab_apply)

    def test_containerlab_pack_role_bindings_are_not_self_recursive(self) -> None:
        stack_paths = [
            self.root
            / "packs"
            / "config"
            / "ansible"
            / "linux"
            / "common"
            / "platform"
            / pack
            / "stack"
            / filename
            for pack, filename in (
                ("60-containerlab-runtime@v1.0", "playbook.yml"),
                ("61-containerlab-lab@v1.0", "playbook.yml"),
                ("61-containerlab-lab@v1.0", "destroy.playbook.yml"),
                ("62-containerlab-healthcheck@v1.0", "playbook.yml"),
                ("63-containerlab-recovery@v1.0", "playbook.yml"),
                ("63-containerlab-recovery@v1.0", "destroy.playbook.yml"),
            )
        ]
        direct_self_binding = re.compile(
            r"(?m)^\s+(containerlab_[a-z0-9_]+):\s+"
            r"[\"']?\{\{\s*\1(?:\s*\|[^}]*)?\s*\}\}[\"']?\s*$"
        )

        violations: list[str] = []
        for path in stack_paths:
            text = path.read_text(encoding="utf-8")
            for match in direct_self_binding.finditer(text):
                violations.append(f"{path.relative_to(self.root)}: {match.group(0).strip()}")

        self.assertEqual(violations, [])

    def test_development_pin_targets_current_containerlab_collection_commit(self) -> None:
        path = self.root / "tools" / "setup" / "requirements" / "ansible.hybridops.git.json"
        payload = json.loads(path.read_text(encoding="utf-8"))
        app = next(item for item in payload["collections"] if item["name"] == "hybridops.app")
        self.assertEqual(app["ref"], "1ca8d662f574ffa69c0d24043af058cbe5833f27")
