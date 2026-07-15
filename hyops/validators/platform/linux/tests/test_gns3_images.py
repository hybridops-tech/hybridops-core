"""Tests for the GNS3 image module validator."""

from copy import deepcopy
from pathlib import Path
import unittest

import yaml

from hyops.validators.platform.linux.gns3_images import validate


REPO_ROOT = Path(__file__).resolve().parents[5]
MODULE_ROOT = REPO_ROOT / "modules" / "platform" / "linux" / "gns3-images"


def valid_inputs() -> dict:
    spec = yaml.safe_load((MODULE_ROOT / "spec.yml").read_text(encoding="utf-8"))
    example = yaml.safe_load(
        (MODULE_ROOT / "examples" / "inputs.min.yml").read_text(encoding="utf-8")
    )
    inputs = deepcopy(spec["inputs"]["defaults"])
    inputs.update(example)
    return inputs


class GNS3ImagesValidatorTests(unittest.TestCase):
    def test_minimal_example_is_valid(self) -> None:
        validate(valid_inputs())

    def test_invalid_image_declarations_are_rejected(self) -> None:
        cases = {
            "empty list": [],
            "unsafe filename": [
                {
                    "name": "test",
                    "url": "https://example.test/image.qcow2",
                    "filename": "../image.qcow2",
                    "checksum": "sha256:" + "a" * 64,
                    "disk_type": "hda",
                }
            ],
            "missing checksum": [
                {
                    "name": "test",
                    "url": "https://example.test/image.qcow2",
                    "filename": "image.qcow2",
                    "disk_type": "hda",
                }
            ],
            "unsupported URL": [
                {
                    "name": "test",
                    "url": "file:///tmp/image.qcow2",
                    "filename": "image.qcow2",
                    "checksum": "sha256:" + "a" * 64,
                    "disk_type": "hda",
                }
            ],
        }
        for label, images in cases.items():
            with self.subTest(label=label):
                inputs = valid_inputs()
                inputs["gns3_images_items"] = images
                with self.assertRaises(ValueError):
                    validate(inputs)

    def test_duplicate_names_and_filenames_are_rejected(self) -> None:
        for key in ("name", "filename"):
            with self.subTest(key=key):
                inputs = valid_inputs()
                duplicate = deepcopy(inputs["gns3_images_items"][0])
                duplicate["name"] = "Another image"
                duplicate["filename"] = "another.iso"
                duplicate[key] = inputs["gns3_images_items"][0][key]
                inputs["gns3_images_items"].append(duplicate)
                with self.assertRaises(ValueError):
                    validate(inputs)


if __name__ == "__main__":
    unittest.main()
