"""Tests for the Containerlab lab module validator."""

from copy import deepcopy
from pathlib import Path
import unittest

import yaml

from hyops.validators.platform.linux.containerlab_lab import validate


REPO_ROOT = Path(__file__).resolve().parents[5]
MODULE_ROOT = REPO_ROOT / "modules" / "platform" / "linux" / "containerlab-lab"


def valid_inputs() -> dict:
    spec = yaml.safe_load((MODULE_ROOT / "spec.yml").read_text(encoding="utf-8"))
    example = yaml.safe_load(
        (MODULE_ROOT / "examples" / "inputs.min.yml").read_text(encoding="utf-8")
    )
    inputs = deepcopy(spec["inputs"]["defaults"])
    inputs.update(example)
    inputs["target_host"] = "0.0.0.0"
    return inputs


class ContainerlabLabValidatorTests(unittest.TestCase):
    def test_default_contract_is_valid(self) -> None:
        validate(valid_inputs())

    def test_local_image_archive_is_valid(self) -> None:
        inputs = valid_inputs()
        inputs["containerlab_lab_local_image_archives"] = [
            {
                "path": "/opt/images/cisco-iol.tar",
                "image": "vrnetlab/cisco_iol:17.15.01",
                "sha256": "a" * 64,
            }
        ]
        validate(inputs)

    def test_relative_archive_path_is_rejected(self) -> None:
        inputs = valid_inputs()
        inputs["containerlab_lab_local_image_archives"] = [
            {
                "path": "images/cisco-iol.tar",
                "image": "vrnetlab/cisco_iol:17.15.01",
            }
        ]
        with self.assertRaisesRegex(ValueError, "absolute controller path"):
            validate(inputs)

    def test_invalid_archive_digest_is_rejected(self) -> None:
        inputs = valid_inputs()
        inputs["containerlab_lab_local_image_archives"] = [
            {
                "path": "/opt/images/cisco-iol.tar",
                "image": "vrnetlab/cisco_iol:17.15.01",
                "sha256": "not-a-digest",
            }
        ]
        with self.assertRaisesRegex(ValueError, "64 lowercase hex"):
            validate(inputs)

    def test_duplicate_expected_image_is_rejected(self) -> None:
        inputs = valid_inputs()
        archive = {
            "path": "/opt/images/cisco-iol.tar",
            "image": "vrnetlab/cisco_iol:17.15.01",
        }
        inputs["containerlab_lab_local_image_archives"] = [archive, archive]
        with self.assertRaisesRegex(ValueError, "duplicates"):
            validate(inputs)


if __name__ == "__main__":
    unittest.main()
