"""Tests for environment-scoped blueprint overlay selection."""

from __future__ import annotations

from types import SimpleNamespace
import tempfile
import unittest
from pathlib import Path

import yaml

from hyops.blueprint.command import _resolve_and_validate


class BlueprintOverlayResolutionTests(unittest.TestCase):
    @staticmethod
    def _write_blueprint(path: Path, blueprint_ref: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            yaml.safe_dump(
                {
                    "api_version": "hybridops/v1",
                    "kind": "BlueprintSpec",
                    "blueprint_ref": blueprint_ref,
                    "mode": "hybrid",
                    "steps": [
                        {
                            "id": "step1",
                            "module_ref": "test/sample-module",
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )

    @staticmethod
    def _namespace(*, root: Path, blueprints_root: Path, file_path: str = ""):
        return SimpleNamespace(
            ref="test/sample@v1",
            file=file_path,
            blueprints_root=str(blueprints_root),
            root=str(root),
            env=None,
        )

    def test_environment_overlay_is_preferred_for_reference(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            catalog = root / "catalog"
            shipped = catalog / "test" / "sample@v1" / "blueprint.yml"
            overlay = root / "runtime" / "config" / "blueprints" / "sample.yml"
            self._write_blueprint(shipped, "test/sample@v1")
            self._write_blueprint(overlay, "test/sample@v1")

            payload = _resolve_and_validate(
                self._namespace(
                    root=root / "runtime",
                    blueprints_root=catalog,
                )
            )

            self.assertEqual(Path(payload["path"]), overlay.resolve())

    def test_shipped_blueprint_is_used_when_overlay_is_absent(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            catalog = root / "catalog"
            shipped = catalog / "test" / "sample@v1" / "blueprint.yml"
            self._write_blueprint(shipped, "test/sample@v1")

            payload = _resolve_and_validate(
                self._namespace(
                    root=root / "runtime",
                    blueprints_root=catalog,
                )
            )

            self.assertEqual(Path(payload["path"]), shipped.resolve())

    def test_explicit_file_overrides_environment_overlay(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            catalog = root / "catalog"
            shipped = catalog / "test" / "sample@v1" / "blueprint.yml"
            overlay = root / "runtime" / "config" / "blueprints" / "sample.yml"
            explicit = root / "runtime" / "config" / "blueprints" / "alternative.yml"
            self._write_blueprint(shipped, "test/sample@v1")
            self._write_blueprint(overlay, "test/sample@v1")
            self._write_blueprint(explicit, "test/sample@v1")

            payload = _resolve_and_validate(
                self._namespace(
                    root=root / "runtime",
                    blueprints_root=catalog,
                    file_path=str(explicit),
                )
            )

            self.assertEqual(Path(payload["path"]), explicit.resolve())

    def test_init_resolution_ignores_existing_environment_overlay(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            catalog = root / "catalog"
            shipped = catalog / "test" / "sample@v1" / "blueprint.yml"
            overlay = root / "runtime" / "config" / "blueprints" / "sample.yml"
            self._write_blueprint(shipped, "test/sample@v1")
            self._write_blueprint(overlay, "test/sample@v1")

            payload = _resolve_and_validate(
                self._namespace(
                    root=root / "runtime",
                    blueprints_root=catalog,
                ),
                allow_runtime_overlay=False,
            )

            self.assertEqual(Path(payload["path"]), shipped.resolve())

    def test_overlay_reference_mismatch_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            catalog = root / "catalog"
            shipped = catalog / "test" / "sample@v1" / "blueprint.yml"
            overlay = root / "runtime" / "config" / "blueprints" / "sample.yml"
            self._write_blueprint(shipped, "test/sample@v1")
            self._write_blueprint(overlay, "test/other@v1")

            with self.assertRaisesRegex(ValueError, "initialized blueprint ref mismatch"):
                _resolve_and_validate(
                    self._namespace(
                        root=root / "runtime",
                        blueprints_root=catalog,
                    )
                )


if __name__ == "__main__":
    unittest.main()
