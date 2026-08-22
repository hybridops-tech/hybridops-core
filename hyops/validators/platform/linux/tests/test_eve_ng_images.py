"""Tests for the EVE-NG image module validator."""

from copy import deepcopy
from pathlib import Path
import unittest

import yaml

from hyops.validators.platform.linux.eve_ng_images import validate


REPO_ROOT = Path(__file__).resolve().parents[5]
MODULE_ROOT = REPO_ROOT / "modules" / "platform" / "linux" / "eve-ng-images"


def valid_inputs() -> dict:
    spec = yaml.safe_load((MODULE_ROOT / "spec.yml").read_text(encoding="utf-8"))
    inputs = deepcopy(spec["inputs"]["defaults"])
    inputs.update(
        {
            "target_host": "127.0.0.1",
            "eveng_images_list": [
                {
                    "url": "https://example.test/iol.bin",
                    "name": "iol.bin",
                    "type": "iol",
                }
            ],
        }
    )
    return inputs


class EVENGImagesValidatorTests(unittest.TestCase):
    def test_optional_iol_license_is_valid(self) -> None:
        inputs = valid_inputs()
        inputs["eveng_images_list"][0]["label"] = "Cisco IOL test image"
        validate(inputs)

    def test_image_label_must_not_be_empty(self) -> None:
        inputs = valid_inputs()
        inputs["eveng_images_list"][0]["label"] = ""

        with self.assertRaisesRegex(ValueError, "label"):
            validate(inputs)

    def test_required_iol_license_must_be_preflighted(self) -> None:
        inputs = valid_inputs()
        inputs["eveng_images_iol_license_required"] = True

        with self.assertRaisesRegex(ValueError, "required_env must include"):
            validate(inputs)

        inputs["required_env"] = ["EVENG_IOL_LICENSE"]
        validate(inputs)

    def test_iol_license_environment_name_must_not_be_empty(self) -> None:
        inputs = valid_inputs()
        inputs["eveng_images_iol_license_env"] = ""
        with self.assertRaises(ValueError):
            validate(inputs)


if __name__ == "__main__":
    unittest.main()
