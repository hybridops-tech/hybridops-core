"""Tests for reusable module contract validation."""

from __future__ import annotations

import unittest

from hyops.validators.contract import validate_contract
from hyops.validators.registry import ModuleValidationError


class ContractValidatorTests(unittest.TestCase):
    """Unit tests for validate_contract."""

    def test_valid_contract_returns_original_inputs(self) -> None:
        inputs = {
            "host": "example.com",
            "port": 443,
        }

        result = validate_contract(
            inputs,
            {
                "host": str,
                "port": int,
            },
        )

        self.assertIs(result, inputs)

    def test_missing_required_field_raises_error(self) -> None:
        inputs = {
            "host": "example.com",
        }

        with self.assertRaisesRegex(
            ModuleValidationError,
            r"inputs\.port is required",
        ):
            validate_contract(
                inputs,
                {
                    "host": str,
                    "port": int,
                },
            )

    def test_wrong_field_type_raises_error(self) -> None:
        inputs = {
            "host": "example.com",
            "port": "443",
        }

        with self.assertRaisesRegex(
            ModuleValidationError,
            r"inputs\.port must be of type int",
        ):
            validate_contract(
                inputs,
                {
                    "host": str,
                    "port": int,
                },
            )

    def test_boolean_is_not_accepted_as_integer(self) -> None:
        inputs = {
            "port": True,
        }

        with self.assertRaisesRegex(
            ModuleValidationError,
            r"inputs\.port must be an integer",
        ):
            validate_contract(
                inputs,
                {
                    "port": int,
                },
            )

    def test_non_mapping_inputs_raise_error(self) -> None:
        with self.assertRaisesRegex(
            ModuleValidationError,
            r"inputs must be a mapping",
        ):
            validate_contract(
                ["host", "example.com"],
                {
                    "host": str,
                },
            )

    def test_empty_required_contract_accepts_mapping(self) -> None:
        inputs = {
            "optional": "value",
        }

        result = validate_contract(inputs, {})

        self.assertIs(result, inputs)


if __name__ == "__main__":
    unittest.main()
