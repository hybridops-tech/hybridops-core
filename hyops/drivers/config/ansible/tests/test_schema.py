from __future__ import annotations

import unittest

from hyops.drivers.config.ansible.schema import validate_execution_schema


class ExecutionSchemaTest(unittest.TestCase):
    def test_accepts_declared_operation_prerequisites(self) -> None:
        validate_execution_schema(
            {
                "driver": "config/ansible",
                "profile": "onprem-linux@v1.0",
                "pack_ref": {"id": "linux/example@v1"},
                "required_collections": ["ansible.posix"],
                "required_roles": ["geerlingguy.postgresql"],
            }
        )

    def test_rejects_invalid_operation_prerequisites(self) -> None:
        with self.assertRaisesRegex(ValueError, "required_collections"):
            validate_execution_schema(
                {
                    "driver": "config/ansible",
                    "profile": "onprem-linux@v1.0",
                    "pack_ref": {"id": "linux/example@v1"},
                    "required_collections": "ansible.posix",
                }
            )


if __name__ == "__main__":
    unittest.main()
