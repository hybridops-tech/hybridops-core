import unittest

from hyops.runtime.module_state_contracts import (
    resolve_postgresql_dr_source_contract_from_state,
)


class PostgreSqlDrSourceContractTests(unittest.TestCase):
    def test_destroy_does_not_require_live_source_state(self) -> None:
        inputs = {
            "_hyops_lifecycle_command": "destroy",
            "source_state_ref": "platform/onprem/postgresql-dr-source#retired-source",
        }

        resolve_postgresql_dr_source_contract_from_state(inputs, state_root=None)

    def test_apply_still_requires_source_state(self) -> None:
        inputs = {
            "_hyops_lifecycle_command": "apply",
            "source_state_ref": "platform/onprem/postgresql-dr-source#missing-source",
        }

        with self.assertRaisesRegex(ValueError, "requires runtime state_dir"):
            resolve_postgresql_dr_source_contract_from_state(inputs, state_root=None)


if __name__ == "__main__":
    unittest.main()
