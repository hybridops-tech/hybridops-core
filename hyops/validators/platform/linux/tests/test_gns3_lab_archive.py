"""Tests for the GNS3 lab archive module validator."""

from copy import deepcopy
from pathlib import Path
import unittest

import yaml

from hyops.validators.platform.linux.gns3_lab_archive import validate


REPO_ROOT = Path(__file__).resolve().parents[5]
MODULE_ROOT = REPO_ROOT / "modules" / "platform" / "linux" / "gns3-lab-archive"


def valid_inputs() -> dict:
    spec = yaml.safe_load((MODULE_ROOT / "spec.yml").read_text(encoding="utf-8"))
    inputs = deepcopy(spec["inputs"]["defaults"])
    inputs.update(
        {
            "target_host": "127.0.0.1",
            "connectivity_check": False,
        }
    )
    return inputs


class GNS3LabArchiveValidatorTests(unittest.TestCase):
    def test_export_defaults_are_valid(self) -> None:
        validate(valid_inputs())

    def test_restore_requires_archive_and_checksum(self) -> None:
        inputs = valid_inputs()
        inputs["gns3_lab_archive_action"] = "restore"
        with self.assertRaises(ValueError):
            validate(inputs)

    def test_restore_accepts_verified_archive(self) -> None:
        inputs = valid_inputs()
        inputs.update(
            {
                "gns3_lab_archive_action": "restore",
                "gns3_lab_archive_path": "/tmp/labs.tar.gz",
                "gns3_lab_archive_expected_sha256": "a" * 64,
                "gns3_lab_archive_overwrite": True,
            }
        )
        validate(inputs)

    def test_relative_data_root_is_rejected(self) -> None:
        inputs = valid_inputs()
        inputs["gns3_lab_archive_data_root"] = "var/lib/gns3"
        with self.assertRaisesRegex(ValueError, "absolute path"):
            validate(inputs)

    def test_boolean_settings_are_required(self) -> None:
        inputs = valid_inputs()
        inputs["gns3_lab_archive_include_images"] = "false"
        with self.assertRaisesRegex(ValueError, "must be a boolean"):
            validate(inputs)


if __name__ == "__main__":
    unittest.main()
