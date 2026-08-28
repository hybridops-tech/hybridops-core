from pathlib import Path
from unittest import TestCase

import yaml


class EVENGImagesModuleTest(TestCase):
    def setUp(self) -> None:
        root = Path(__file__).resolve().parents[2]
        self.spec = yaml.safe_load(
            (root / "modules/platform/linux/eve-ng-images/spec.yml").read_text()
        )
        self.playbook = yaml.safe_load(
            (
                root
                / "packs/config/ansible/linux/common/platform/"
                "41-eve-ng-images@v1.0/stack/playbook.yml"
            ).read_text()
        )[0]

    def test_module_publishes_requested_and_installed_counts(self) -> None:
        published = self.spec["outputs"]["publish"]
        self.assertIn("eveng_images_requested_count", published)
        self.assertIn("eveng_images_installed_count", published)

    def test_stack_verifies_the_discovered_image_count(self) -> None:
        verification = self.playbook["post_tasks"][0]["ansible.builtin.assert"]
        self.assertIn(
            "eveng_images_requested_count | default(0) | int",
            verification["that"][1],
        )
        output_document = self.playbook["post_tasks"][2]["ansible.builtin.copy"][
            "content"
        ]
        self.assertIn("'eveng_images_requested_count'", output_document)


if __name__ == "__main__":
    import unittest

    unittest.main()
