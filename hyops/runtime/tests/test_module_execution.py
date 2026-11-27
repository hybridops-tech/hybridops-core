from pathlib import Path
from unittest import TestCase

from hyops.runtime.module_resolve import resolve_module_execution


REPO_ROOT = Path(__file__).resolve().parents[3]


class ModuleExecutionTest(TestCase):
    def test_operation_prerequisites_are_resolved(self) -> None:
        execution = resolve_module_execution(
            "platform/onprem/postgresql-core",
            REPO_ROOT / "modules",
        )

        self.assertEqual(
            execution["required_collections"],
            ["community.general", "community.postgresql"],
        )
        self.assertEqual(
            execution["required_roles"],
            ["geerlingguy.postgresql"],
        )

    def test_transitive_operation_prerequisites_are_declared(self) -> None:
        execution = resolve_module_execution(
            "platform/onprem/rke2-cluster",
            REPO_ROOT / "modules",
        )

        self.assertEqual(
            execution["required_collections"],
            ["rancherfederal.rke2_ansible", "ansible.utils"],
        )
