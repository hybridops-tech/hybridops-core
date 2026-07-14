from pathlib import Path
from unittest import TestCase

import yaml


class GNS3ImagesModuleTest(TestCase):
    def setUp(self) -> None:
        root = Path(__file__).resolve().parents[2]
        self.spec = yaml.safe_load(
            (root / "modules/platform/linux/gns3-images/spec.yml").read_text()
        )

    def test_module_uses_collection_role_and_vault_password(self) -> None:
        defaults = self.spec["inputs"]["defaults"]
        self.assertEqual(defaults["gns3_images_role_fqcn"], "hybridops.app.gns3_images")
        self.assertEqual(defaults["required_env"], ["GNS3_SERVER_PASSWORD"])

    def test_module_publishes_image_and_template_counts(self) -> None:
        self.assertEqual(
            self.spec["outputs"]["publish"],
            [
                "cap.lab.gns3.images",
                "gns3_images_requested_count",
                "gns3_images_installed_count",
                "gns3_images_template_names",
            ],
        )
