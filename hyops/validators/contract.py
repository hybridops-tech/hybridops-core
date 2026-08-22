"""Reusable validation helpers for module input contracts.

This module provides small, dependency-free helpers for validating the
shape of module inputs before they are passed to execution-specific
validators.

purpose: Shared module contract validation.
maintainer: HybridOps.Tech
"""

from __future__ import annotations

from typing import Any

from hyops.validators.registry import ModuleValidationError


def validate_contract(
    inputs: Any,
    required: dict[str, type[Any]],
) -> dict[str, Any]:
    """Validate required fields and their expected Python types.

    Args:
        inputs: Module input values to validate.
        required: Mapping of required field names to their expected types.

    Returns:
        The original input mapping when validation succeeds.

    Raises:
        ModuleValidationError: If ``inputs`` is not a mapping, a required
            field is missing, or a field has an unexpected type.

    Example:
        >>> validate_contract(
        ...     {"host": "example.com", "port": 443},
        ...     {"host": str, "port": int},
        ... )
        {'host': 'example.com', 'port': 443}
    """
    if not isinstance(inputs, dict):
        raise ModuleValidationError("inputs must be a mapping")

    for field, expected_type in required.items():
        if field not in inputs:
            raise ModuleValidationError(f"inputs.{field} is required")

        value = inputs[field]

        # bool is a subclass of int in Python. Reject it when an integer
        # contract is explicitly requested because True/False should not
        # silently satisfy an integer field.
        if expected_type is int and isinstance(value, bool):
            raise ModuleValidationError(
                f"inputs.{field} must be an integer"
            )

        if not isinstance(value, expected_type):
            raise ModuleValidationError(
                f"inputs.{field} must be of type "
                f"{expected_type.__name__}"
            )

    return inputs
