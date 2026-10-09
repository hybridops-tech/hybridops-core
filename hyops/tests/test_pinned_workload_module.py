"""Contract tests for immutable external workload execution."""

from pathlib import Path
from unittest import TestCase

import yaml


class PinnedWorkloadModuleTest(TestCase):
    def setUp(self) -> None:
        self.root = Path(__file__).resolve().parents[2]
        self.spec = yaml.safe_load(
            (
                self.root
                / "modules/platform/linux/pinned-workload/spec.yml"
            ).read_text(encoding="utf-8")
        )
        self.stack_root = (
            self.root
            / "packs/config/ansible/linux/common/platform/"
            "65-pinned-workload@v1.0/stack"
        )

    def test_module_requires_exact_commit_and_declared_evidence(self) -> None:
        defaults = self.spec["inputs"]["defaults"]
        self.assertEqual(defaults["pinned_workload_revision"], "")
        self.assertEqual(defaults["pinned_workload_evidence_paths"], [])
        self.assertEqual(defaults["pinned_workload_packages"], [])
        self.assertEqual(defaults["pinned_workload_container_image_archives"], [])
        self.assertEqual(
            defaults["pinned_workload_role_fqcn"],
            "hybridops.app.pinned_workload",
        )
        self.assertGreater(
            defaults["execution_timeout_s"],
            defaults["pinned_workload_timeout_s"],
        )

    def test_apply_pack_defaults_evidence_to_environment_artifacts(self) -> None:
        playbook = (self.stack_root / "playbook.yml").read_text(encoding="utf-8")
        self.assertIn("HYOPS_RUNTIME_ROOT", playbook)
        self.assertIn("/artifacts/workloads/", playbook)
        self.assertIn("pinned_workload_evidence_sha256", playbook)
        self.assertIn("pinned_workload_missing_evidence", playbook)
        self.assertIn("pinned_workload_container_images", playbook)

    def test_destroy_pack_removes_only_managed_checkout(self) -> None:
        playbook = yaml.safe_load(
            (self.stack_root / "destroy.playbook.yml").read_text(encoding="utf-8")
        )[0]
        role_task = playbook["tasks"][0]
        self.assertEqual(role_task["vars"]["_pinned_workload_action"], "destroy")

    def test_module_publishes_execution_binding(self) -> None:
        outputs = set(self.spec["outputs"]["publish"])
        self.assertIn("pinned_workload_resolved_commit", outputs)
        self.assertIn("pinned_workload_exit_code", outputs)
        self.assertIn("pinned_workload_evidence_sha256", outputs)
        self.assertIn("pinned_workload_container_images", outputs)


if __name__ == "__main__":
    import unittest

    unittest.main()
