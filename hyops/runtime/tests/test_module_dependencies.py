from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase

from hyops.runtime.module_dependencies import resolve_dependencies
from hyops.runtime.module_state import write_module_state


class PlannedDependencyResolutionTest(TestCase):
    def setUp(self) -> None:
        self.spec = {
            "dependencies": [
                {
                    "module_ref": "core/azure/resource-group",
                    "required": True,
                    "imports": {
                        "resource_group_name": "resource_group_name",
                        "location": "location",
                    },
                }
            ]
        }

    def test_missing_outputs_are_deferred_for_planned_upstream_state(self):
        with TemporaryDirectory() as tmp:
            state_dir = Path(tmp)
            write_module_state(
                state_dir,
                "core/azure/resource-group",
                {"status": "destroyed", "outputs": {}},
            )

            inputs, dependencies, warnings = resolve_dependencies(
                self.spec,
                "core/azure/vnet",
                state_dir,
                assumed_state_ok={"core/azure/resource-group"},
            )

        self.assertEqual(inputs, {})
        self.assertEqual(len(dependencies), 1)
        self.assertTrue(dependencies[0]["deferred"])
        self.assertIn("dependency outputs missing", warnings[0])

    def test_missing_outputs_still_block_without_planned_upstream_state(self):
        with TemporaryDirectory() as tmp:
            state_dir = Path(tmp)
            write_module_state(
                state_dir,
                "core/azure/resource-group",
                {"status": "destroyed", "outputs": {}},
            )

            with self.assertRaisesRegex(ValueError, "dependency outputs missing"):
                resolve_dependencies(
                    self.spec,
                    "core/azure/vnet",
                    state_dir,
                )

    def test_missing_state_is_deferred_for_planned_upstream_state(self):
        with TemporaryDirectory() as tmp:
            inputs, dependencies, warnings = resolve_dependencies(
                self.spec,
                "core/azure/vnet",
                Path(tmp),
                assumed_state_ok={"core/azure/resource-group"},
            )

        self.assertEqual(inputs, {})
        self.assertEqual(len(dependencies), 1)
        self.assertFalse(dependencies[0]["resolved"])
        self.assertTrue(dependencies[0]["deferred"])
        self.assertIn("dependency state unavailable", warnings[0])

    def test_missing_state_still_blocks_without_planned_upstream_state(self):
        with (
            TemporaryDirectory() as tmp,
            self.assertRaisesRegex(ValueError, "dependency state unavailable"),
        ):
            resolve_dependencies(
                self.spec,
                "core/azure/vnet",
                Path(tmp),
            )
