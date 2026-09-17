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

    def test_invalid_remote_owner_is_rejected(self) -> None:
        inputs = valid_inputs()
        inputs["containerlab_lab_remote_owner"] = "bad:user"
        with self.assertRaisesRegex(ValueError, "remote_owner is invalid"):
            validate(inputs)

    def test_destroy_scope_must_be_boolean(self) -> None:
        inputs = valid_inputs()
        inputs["containerlab_lab_destroy_all"] = "false"
        with self.assertRaisesRegex(ValueError, "destroy_all must be a boolean"):
            validate(inputs)

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

    def test_local_iol_image_builds_are_valid(self) -> None:
        inputs = valid_inputs()
        inputs["containerlab_lab_local_image_builds"] = [
            {
                "kind": "cisco_iol",
                "source": "/opt/images/cisco-iol-l3.bin",
                "version": "17.15.01",
                "type": "l3",
                "authorised_use": True,
                "sha256": "b" * 64,
            },
            {
                "kind": "cisco_iol",
                "source": "/opt/images/ioll2-xe-17-18-02.tar.gz",
                "version": "17.18.02",
                "type": "l2",
                "format": "oci_archive",
                "authorised_use": True,
            },
        ]
        validate(inputs)

    def test_local_iol_image_directory_is_valid(self) -> None:
        inputs = valid_inputs()
        inputs["containerlab_lab_local_image_dir"] = "/opt/images/cml"
        inputs["containerlab_lab_local_image_dir_authorised_use"] = True
        validate(inputs)

    def test_local_iol_image_directory_requires_absolute_path(self) -> None:
        inputs = valid_inputs()
        inputs["containerlab_lab_local_image_dir"] = "images/cml"
        inputs["containerlab_lab_local_image_dir_authorised_use"] = True
        with self.assertRaisesRegex(ValueError, "absolute controller path"):
            validate(inputs)

    def test_local_iol_image_directory_requires_authorised_use(self) -> None:
        inputs = valid_inputs()
        inputs["containerlab_lab_local_image_dir"] = "/opt/images/cml"
        with self.assertRaisesRegex(ValueError, "must be true"):
            validate(inputs)

    def test_local_iol_image_directory_and_builds_are_mutually_exclusive(self) -> None:
        inputs = valid_inputs()
        inputs["containerlab_lab_local_image_dir"] = "/opt/images/cml"
        inputs["containerlab_lab_local_image_dir_authorised_use"] = True
        inputs["containerlab_lab_local_image_builds"] = [
            {
                "kind": "cisco_iol",
                "source": "/opt/images/cisco-iol.bin",
                "version": "17.15.01",
                "authorised_use": True,
            }
        ]
        with self.assertRaisesRegex(ValueError, "cannot be combined"):
            validate(inputs)

    def test_local_image_build_requires_authorised_use(self) -> None:
        inputs = valid_inputs()
        build = {
            "kind": "cisco_iol",
            "source": "/opt/images/cisco-iol.bin",
            "version": "17.15.01",
        }
        inputs["containerlab_lab_local_image_builds"] = [build]
        with self.assertRaisesRegex(ValueError, "authorised_use must be a boolean"):
            validate(inputs)

        build["authorised_use"] = False
        with self.assertRaisesRegex(ValueError, "authorised_use must be true"):
            validate(inputs)

    def test_invalid_local_image_build_fields_are_rejected(self) -> None:
        base = {
            "kind": "cisco_iol",
            "source": "/opt/images/cisco-iol.bin",
            "version": "17.15.01",
            "authorised_use": True,
        }
        cases = [
            ("kind", "other", "kind must be cisco_iol"),
            ("source", "images/cisco-iol.bin", "absolute controller path"),
            ("version", "../17.15.01", "valid image version"),
            ("type", "switch", "type must be l3 or l2"),
            ("format", "tar", "format must be binary or oci_archive"),
            ("sha256", "not-a-digest", "64 lowercase hex"),
        ]
        for field, value, error in cases:
            with self.subTest(field=field):
                inputs = valid_inputs()
                build = dict(base)
                build[field] = value
                inputs["containerlab_lab_local_image_builds"] = [build]
                with self.assertRaisesRegex(ValueError, error):
                    validate(inputs)

    def test_oci_archive_requires_dotted_numeric_version(self) -> None:
        inputs = valid_inputs()
        inputs["containerlab_lab_local_image_builds"] = [
            {
                "kind": "cisco_iol",
                "source": "/opt/images/iol-xe-build.tar.gz",
                "version": "17.18.02-build",
                "format": "oci_archive",
                "authorised_use": True,
            }
        ]
        with self.assertRaisesRegex(ValueError, "must be dotted numeric"):
            validate(inputs)

    def test_duplicate_local_image_build_is_rejected(self) -> None:
        inputs = valid_inputs()
        build = {
            "kind": "cisco_iol",
            "source": "/opt/images/cisco-iol.bin",
            "version": "17.15.01",
            "authorised_use": True,
        }
        inputs["containerlab_lab_local_image_builds"] = [build, build]
        with self.assertRaisesRegex(ValueError, "duplicates"):
            validate(inputs)

    def test_archive_and_build_cannot_produce_same_image(self) -> None:
        inputs = valid_inputs()
        inputs["containerlab_lab_local_image_archives"] = [
            {
                "path": "/opt/images/cisco-iol.tar",
                "image": "vrnetlab/cisco_iol:17.15.01",
            }
        ]
        inputs["containerlab_lab_local_image_builds"] = [
            {
                "kind": "cisco_iol",
                "source": "/opt/images/cisco-iol.bin",
                "version": "17.15.01",
                "authorised_use": True,
            }
        ]
        with self.assertRaisesRegex(ValueError, "duplicates a local image archive"):
            validate(inputs)

    def test_image_builder_requires_absolute_root_and_full_revision(self) -> None:
        inputs = valid_inputs()
        inputs["containerlab_lab_image_build_root"] = "containerlab/builds"
        with self.assertRaisesRegex(ValueError, "must be an absolute path"):
            validate(inputs)

        inputs = valid_inputs()
        inputs["containerlab_lab_vrnetlab_revision"] = "main"
        with self.assertRaisesRegex(ValueError, "full lowercase commit SHA"):
            validate(inputs)


if __name__ == "__main__":
    unittest.main()
