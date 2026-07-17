"""Tests for the EVE-NG lab archive module validator."""

from copy import deepcopy
from pathlib import Path
import unittest

import yaml

from hyops.validators.platform.linux.eve_ng_lab_archive import validate


REPO_ROOT = Path(__file__).resolve().parents[5]
MODULE_ROOT = REPO_ROOT / "modules" / "platform" / "linux" / "eve-ng-lab-archive"


def valid_inputs() -> dict:
    spec = yaml.safe_load((MODULE_ROOT / "spec.yml").read_text(encoding="utf-8"))
    inputs = deepcopy(spec["inputs"]["defaults"])
    inputs.update(
        {
            "target_host": "127.0.0.1",
            "ssh_private_key_file": "~/.ssh/id_ed25519",
            "connectivity_check": False,
        }
    )
    return inputs


class EveNgLabArchiveValidatorTests(unittest.TestCase):
    def test_export_defaults_are_valid(self) -> None:
        validate(valid_inputs())

    def test_restore_requires_archive_and_checksum(self) -> None:
        inputs = valid_inputs()
        inputs["eveng_lab_archive_action"] = "restore"
        with self.assertRaises(ValueError):
            validate(inputs)

    def test_restore_accepts_verified_archive(self) -> None:
        inputs = valid_inputs()
        inputs.update(
            {
                "eveng_lab_archive_action": "restore",
                "eveng_lab_archive_path": "/tmp/labs.tar.gz",
                "eveng_lab_archive_expected_sha256": "a" * 64,
            }
        )
        validate(inputs)

    def test_unsafe_folder_is_rejected(self) -> None:
        inputs = valid_inputs()
        inputs["eveng_lab_archive_folders"] = ["../images"]
        with self.assertRaises(ValueError):
            validate(inputs)

    def test_node_state_export_requires_complete_lab_tree(self) -> None:
        inputs = valid_inputs()
        inputs["eveng_lab_archive_include_node_state"] = True
        inputs["eveng_lab_archive_folders"] = ["student"]
        with self.assertRaisesRegex(ValueError, "must be empty"):
            validate(inputs)

    def test_node_state_restore_requires_companion_checksum(self) -> None:
        inputs = valid_inputs()
        inputs.update(
            {
                "eveng_lab_archive_action": "restore",
                "eveng_lab_archive_path": "/tmp/labs.tar.gz",
                "eveng_lab_archive_expected_sha256": "a" * 64,
                "eveng_lab_archive_restore_node_state": True,
                "eveng_lab_archive_node_state_path": "/tmp/nodes.tar.gz",
            }
        )
        with self.assertRaises(ValueError):
            validate(inputs)


if __name__ == "__main__":
    unittest.main()
