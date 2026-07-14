from pathlib import Path
import unittest

import yaml


REPO_ROOT = Path(__file__).resolve().parents[2]


class GNS3ServerModuleTests(unittest.TestCase):
    def setUp(self) -> None:
        spec_path = REPO_ROOT / "modules/platform/linux/gns3-server/spec.yml"
        self.spec = yaml.safe_load(spec_path.read_text(encoding="utf-8"))

    def test_module_uses_provider_neutral_ansible_pack(self) -> None:
        self.assertEqual(self.spec["module_ref"], "platform/linux/gns3-server")
        self.assertEqual(self.spec["execution"]["driver"], "config/ansible")
        self.assertEqual(
            self.spec["execution"]["pack_ref"]["id"],
            "linux/common/platform/44-gns3-server@v1.0",
        )

    def test_module_requires_server_password(self) -> None:
        defaults = self.spec["inputs"]["defaults"]
        self.assertEqual(defaults["required_env"], ["GNS3_SERVER_PASSWORD"])
        self.assertTrue(defaults["load_vault_env"])
        self.assertEqual(defaults["required_env_destroy"], [])

    def test_module_publishes_access_contract(self) -> None:
        self.assertEqual(
            self.spec["outputs"]["publish"],
            ["gns3_url", "gns3_api_port", "cap.lab.gns3"],
        )


if __name__ == "__main__":
    unittest.main()
