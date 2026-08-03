"""Tests for offline blueprint catalog validation check."""

from __future__ import annotations

import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path
import yaml

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

spec = importlib.util.spec_from_file_location(
    "check_blueprint_catalog", REPO_ROOT / "tools" / "ci" / "check-blueprint-catalog.py"
)
check_blueprint_module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(check_blueprint_module)
check_blueprint_catalog = check_blueprint_module.check_blueprint_catalog


class BlueprintCatalogTests(unittest.TestCase):
    def test_check_blueprint_catalog_valid(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            repo = Path(tmp_dir)
            blueprints = repo / "blueprints" / "test" / "sample@v1"
            blueprints.mkdir(parents=True)
            modules = repo / "modules" / "test" / "sample-module"
            modules.mkdir(parents=True)
            (modules / "spec.yml").write_text("kind: ModuleSpec\n")

            bp_spec = {
                "api_version": "hybridops/v1",
                "kind": "BlueprintSpec",
                "blueprint_ref": "test/sample@v1",
                "mode": "hybrid",
                "steps": [
                    {
                        "id": "step1",
                        "module_ref": "test/sample-module",
                    }
                ],
            }
            (blueprints / "blueprint.yml").write_text(yaml.dump(bp_spec))

            failures, count = check_blueprint_catalog(repo)
            self.assertEqual(failures, [])
            self.assertEqual(count, 1)

    def test_check_blueprint_catalog_ref_mismatch(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            repo = Path(tmp_dir)
            blueprints = repo / "blueprints" / "test" / "sample@v1"
            blueprints.mkdir(parents=True)

            bp_spec = {
                "api_version": "hybridops/v1",
                "kind": "BlueprintSpec",
                "blueprint_ref": "wrong/ref@v1",
                "mode": "hybrid",
                "steps": [
                    {
                        "id": "step1",
                        "module_ref": "test/sample-module",
                    }
                ],
            }
            (blueprints / "blueprint.yml").write_text(yaml.dump(bp_spec))

            failures, count = check_blueprint_catalog(repo)
            self.assertTrue(any("blueprint_ref mismatch" in f for f in failures))

    def test_check_blueprint_catalog_missing_module(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            repo = Path(tmp_dir)
            blueprints = repo / "blueprints" / "test" / "sample@v1"
            blueprints.mkdir(parents=True)

            bp_spec = {
                "api_version": "hybridops/v1",
                "kind": "BlueprintSpec",
                "blueprint_ref": "test/sample@v1",
                "mode": "hybrid",
                "steps": [
                    {
                        "id": "step1",
                        "module_ref": "nonexistent/sample-module",
                    }
                ],
            }
            (blueprints / "blueprint.yml").write_text(yaml.dump(bp_spec))

            failures, count = check_blueprint_catalog(repo)
            self.assertTrue(any("does not resolve to spec.yml" in f for f in failures))

    def test_check_blueprint_catalog_malformed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            repo = Path(tmp_dir)
            blueprints = repo / "blueprints" / "test" / "sample@v1"
            blueprints.mkdir(parents=True)
            (blueprints / "blueprint.yml").write_text("invalid: yaml: [")

            failures, count = check_blueprint_catalog(repo)
            self.assertTrue(len(failures) > 0)

    def test_check_blueprint_catalog_unknown_step_key(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            repo = Path(tmp_dir)
            blueprints = repo / "blueprints" / "test" / "sample@v1"
            blueprints.mkdir(parents=True)
            modules = repo / "modules" / "test" / "sample-module"
            modules.mkdir(parents=True)
            (modules / "spec.yml").write_text("kind: ModuleSpec\n")

            bp_spec = {
                "api_version": "hybridops/v1",
                "kind": "BlueprintSpec",
                "blueprint_ref": "test/sample@v1",
                "mode": "hybrid",
                "steps": [
                    {
                        "id": "step1",
                        "module_ref": "test/sample-module",
                        "firewall_name": "invalid",
                    }
                ],
            }
            (blueprints / "blueprint.yml").write_text(yaml.dump(bp_spec))

            failures, count = check_blueprint_catalog(repo)
            self.assertTrue(any("step 'step1' has unknown keys: firewall_name" in f for f in failures))


if __name__ == "__main__":
    unittest.main()