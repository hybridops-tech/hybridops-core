"""Lifecycle tests for the bounded local artifact driver."""

from __future__ import annotations

import json
import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from hyops.drivers.local.artifact import driver
from hyops.runtime.paths import RuntimePaths


class LocalArtifactDriverTests(unittest.TestCase):
    @staticmethod
    def _artifact(root: Path) -> Path:
        return root / "state" / "managed" / "local-artifact" / "quickstart.json"

    def _request(self, root: Path, command: str, run_id: str) -> dict:
        paths = RuntimePaths.from_root(root)
        for path in (paths.root, paths.state_dir, paths.logs_dir):
            path.mkdir(parents=True, exist_ok=True)
        return {
            "command": command,
            "run_id": run_id,
            "module_ref": "core/local/quickstart",
            "inputs": {
                "operation_id": "first-governed-operation",
                "declared_outcome": "local-artifact-present",
            },
            "execution": {
                "driver": "local/artifact",
                "profile": "local@v1.0",
                "pack_id": "core/00-quickstart@v1.0",
            },
            "runtime": {
                "root": str(paths.root),
                "state_dir": str(paths.state_dir),
            },
            "evidence_dir": str(paths.logs_dir / run_id),
        }

    def test_apply_is_verified_and_idempotent(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            first = driver.run(self._request(root, "apply", "apply-1"))
            second = driver.run(self._request(root, "apply", "apply-2"))
            artifact = self._artifact(root)

            self.assertEqual(first["status"], "ok")
            self.assertEqual(first["normalized_outputs"]["action"], "created")
            self.assertTrue(
                first["normalized_outputs"]["published_outputs"]["quickstart.verified"]
            )
            self.assertEqual(second["status"], "ok")
            self.assertEqual(second["normalized_outputs"]["action"], "unchanged")
            self.assertTrue(artifact.is_file())
            self.assertEqual(artifact.stat().st_mode & 0o777, 0o600)

    def test_preflight_rejects_drifted_artifact(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            driver.run(self._request(root, "apply", "apply-1"))
            artifact = self._artifact(root)
            artifact.write_text(json.dumps({"changed": True}), encoding="utf-8")
            request = self._request(root, "preflight", "preflight-1")
            request["lifecycle_command"] = "apply"

            result = driver.run(request)

            self.assertEqual(result["status"], "error")
            self.assertIn("differs from declared intent", result["error"])

    def test_destroy_recovers_invalid_artifact_without_recursive_deletion(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            artifact = self._artifact(root)
            artifact.parent.mkdir(parents=True)
            artifact.write_text("not-json", encoding="utf-8")
            retained = artifact.parent / "operator-file.txt"
            retained.write_text("retain", encoding="utf-8")

            result = driver.run(self._request(root, "destroy", "destroy-1"))

            self.assertEqual(result["status"], "ok")
            self.assertEqual(result["normalized_outputs"]["action"], "removed")
            self.assertFalse(artifact.exists())
            self.assertEqual(retained.read_text(encoding="utf-8"), "retain")

    def test_symbolic_link_artifact_is_rejected(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            artifact = self._artifact(root)
            artifact.parent.mkdir(parents=True)
            outside = root / "outside.json"
            outside.write_text("{}", encoding="utf-8")
            artifact.symlink_to(outside)

            result = driver.run(self._request(root, "apply", "apply-1"))

            self.assertEqual(result["status"], "error")
            self.assertIn("symbolic link", result["error"])
            self.assertEqual(outside.read_text(encoding="utf-8"), "{}")

    def test_symbolic_link_parent_is_rejected(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp) / "runtime"
            state = root / "state"
            outside = Path(tmp) / "outside"
            state.mkdir(parents=True)
            outside.mkdir()
            (state / "managed").symlink_to(outside, target_is_directory=True)

            result = driver.run(self._request(root, "apply", "apply-1"))

            self.assertEqual(result["status"], "error")
            self.assertIn("symbolic link", result["error"])
            self.assertEqual(list(outside.iterdir()), [])

    def test_oversized_artifact_is_rejected_before_json_parsing(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            artifact = self._artifact(root)
            artifact.parent.mkdir(parents=True)
            artifact.write_bytes(b" " * (64 * 1024 + 1))

            result = driver.run(self._request(root, "apply", "apply-1"))

            self.assertEqual(result["status"], "error")
            self.assertIn("size limit", result["error"])

    def test_pack_contract_drives_bounded_path_and_outputs(self) -> None:
        with TemporaryDirectory() as tmp:
            base = Path(tmp).resolve()
            root = base / "runtime"
            pack = (
                base
                / "packs"
                / "local"
                / "artifact"
                / "test"
                / "data-driven@v1.0"
                / "stack"
            )
            pack.mkdir(parents=True)
            (pack / "contract.yml").write_text(
                "\n".join(
                    (
                        "api_version: hybridops/v1",
                        "kind: LocalArtifactContract",
                        "artifact:",
                        '  relative_path: "tests/contract.json"',
                        "  module_refs:",
                        '    - "core/local/quickstart"',
                        '  output_prefix: "contract_test"',
                        '  capability: "cap.contract.test"',
                    )
                )
                + "\n",
                encoding="utf-8",
            )
            request = self._request(root, "apply", "apply-1")
            request["execution"]["pack_id"] = "test/data-driven@v1.0"

            with patch.dict(os.environ, {"HYOPS_PACKS_ROOT": str(base / "packs")}):
                result = driver.run(request)

            outputs = result["normalized_outputs"]["published_outputs"]
            artifact = (
                root
                / "state"
                / "managed"
                / "local-artifact"
                / "tests"
                / "contract.json"
            )
            self.assertEqual(result["status"], "ok")
            self.assertTrue(artifact.is_file())
            self.assertEqual(outputs["cap.contract.test"], "ready")
            self.assertEqual(outputs["contract_test.artifact_path"], str(artifact))

    def test_profile_policy_must_preserve_credential_free_boundary(self) -> None:
        with TemporaryDirectory() as tmp:
            base = Path(tmp).resolve()
            profiles = base / "profiles"
            profiles.mkdir()
            (profiles / "local@v1.0.profile.yml").write_text(
                "\n".join(
                    (
                        "api_version: hybridops/v1",
                        "kind: DriverProfile",
                        'profile_ref: "local@v1.0"',
                        'driver: "local/artifact"',
                        "policy:",
                        "  credentials: []",
                        "  external_tools: []",
                        "  network_access: true",
                    )
                )
                + "\n",
                encoding="utf-8",
            )

            with patch.object(driver, "_PROFILES_DIR", profiles):
                result = driver.run(
                    self._request(base / "runtime", "apply", "apply-1")
                )

            self.assertEqual(result["status"], "error")
            self.assertIn("disable network access", result["error"])

    def test_invalid_pack_reference_returns_error_envelope(self) -> None:
        with TemporaryDirectory() as tmp:
            request = self._request(Path(tmp), "apply", "apply-1")
            request["execution"]["pack_id"] = "../outside"

            result = driver.run(request)

            self.assertEqual(result["status"], "error")
            self.assertIn("must not contain", result["error"])


if __name__ == "__main__":
    unittest.main()
