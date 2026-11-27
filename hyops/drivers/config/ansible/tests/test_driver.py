from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from hyops.drivers.config.ansible.driver import run


class AnsibleDriverTests(unittest.TestCase):
    def test_noop_postgresql_destroy_skips_operation_prerequisites(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            root = Path(raw_tmp)
            request = {
                "evidence_dir": str(root / "evidence"),
                "run_id": "destroy-test",
                "module_ref": "platform/onprem/postgresql-ha",
                "command": "destroy",
                "execution": {
                    "driver": "config/ansible",
                    "profile": "test",
                    "pack_id": "platform/postgresql-ha",
                    "required_collections": ["vitabaks.autobase"],
                },
                "runtime": {
                    "root": str(root / "runtime"),
                    "work_dir": str(root / "work"),
                },
                "inputs": {
                    "inventory_state_ref": "platform/onprem/platform-vm",
                },
            }

            with (
                patch(
                    "hyops.drivers.config.ansible.driver.load_profile",
                    return_value=({}, None, ""),
                ),
                patch(
                    "hyops.drivers.config.ansible.driver.resolve_policy_defaults",
                    return_value=(60, 0, False),
                ),
                patch(
                    "hyops.drivers.config.ansible.driver.resolve_ansible_cfg",
                    return_value={
                        "bin": "ansible-playbook",
                        "playbook_file": "playbook.yml",
                        "inventory_file": "inventory.ini",
                    },
                ),
                patch(
                    "hyops.drivers.config.ansible.driver.shutil.which",
                    return_value="/usr/bin/ansible-playbook",
                ),
                patch(
                    "hyops.drivers.config.ansible.driver.resolve_pack_stack",
                    return_value=SimpleNamespace(stack_dir=root / "pack"),
                ),
                patch(
                    "hyops.drivers.config.ansible.driver.read_module_state",
                    return_value={"status": "destroyed"},
                ),
                patch(
                    "hyops.drivers.config.ansible.driver.prepare_ansible_controller_env"
                ) as prepare_controller,
                patch(
                    "hyops.drivers.config.ansible.driver.missing_operation_prerequisites"
                ) as check_prerequisites,
            ):
                result = run(request)

        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["normalized_outputs"]["cap.db.postgresql_ha"], "absent")
        prepare_controller.assert_not_called()
        check_prerequisites.assert_not_called()


if __name__ == "__main__":
    unittest.main()
