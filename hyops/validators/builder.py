"""Helper to build validators from module specifications.

purpose: Generate validators that enforce required fields and types
maintainer: HybridOps.Tech
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable
import yaml

from hyops.validators.registry import ModuleValidationError


def build_validator_from_spec(spec_path: Path) -> Callable[[dict[str, Any]], None]:
    """Build a validator function from a module spec.

    Args:
        spec_path: Path to module spec.yml

    Returns:
        Validator function that checks inputs against spec
    """
    spec = yaml.safe_load(spec_path.read_text())
    defaults = spec.get("inputs", {}).get("defaults", {})

    # Extract type information from defaults
    def_types: dict[str, type] = {}
    for key, value in defaults.items():
        if value is None:
            def_types[key] = type(None)
        else:
            def_types[key] = type(value)

    allowed_keys = set(defaults.keys()) | {
        "_hyops_lifecycle_command",
        "_hyops_invocation_command",
    }

    def validator(inputs: dict[str, Any]) -> None:
        """Validate inputs against module spec."""

        # Check for unknown keys
        unknown = sorted(str(k) for k in inputs if str(k) not in allowed_keys)
        if unknown:
            raise ModuleValidationError(f"unknown inputs: {', '.join(unknown)}")

        # Check types of provided values
        for key, value in inputs.items():
            if key in def_types and value is not None:
                expected_type = def_types[key]
                if not isinstance(value, expected_type):
                    raise ModuleValidationError(
                        f"input {key!r} must be {expected_type.__name__}, "
                        f"got {type(value).__name__}"
                    )

    return validator


def get_validator_from_spec(module_ref: str) -> Callable[[dict[str, Any]], None]:
    """Get validator for a module by resolving its spec file.

    Args:
        module_ref: Module reference (e.g., "platform/linux/containerlab")

    Returns:
        Validator function

    Raises:
        FileNotFoundError: If module spec not found
    """
    # Convert module_ref to spec path
    # e.g., "platform/linux/containerlab" -> "modules/platform/linux/containerlab/spec.yml"
    parts = module_ref.split("/")
    spec_path = Path("modules") / parts[0] / parts[1] / "-".join(parts[2:]) / "spec.yml"

    if not spec_path.exists():
        raise FileNotFoundError(f"Module spec not found: {spec_path}")

    return build_validator_from_spec(spec_path)
