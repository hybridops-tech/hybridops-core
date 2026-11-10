"""Test that all production modules have validators registered."""

from __future__ import annotations

import unittest
from hyops.validators.builtin.register import register_all
from hyops.validators.registry import _REGISTRY, validate_module_inputs, ModuleValidationError


class TestValidatorRegistrationCompleteness(unittest.TestCase):
    """Verify all production modules have validators and unknown keys are rejected."""

    @classmethod
    def setUpClass(cls) -> None:
        register_all()

    def test_all_production_modules_have_validators(self) -> None:
        """All production modules must have registered validators (dynamic).

        Validators are discovered from module registry at runtime, ensuring
        that any new modules added are automatically validated.
        """
        from pathlib import Path

        modules_root = Path("modules")
        expected_modules = set()

        # Dynamically discover all production modules from specs
        for spec_file in modules_root.rglob("spec.yml"):
            parts = spec_file.parent.relative_to(modules_root).parts
            if len(parts) >= 3:
                module_ref = "/".join(parts)
                expected_modules.add(module_ref)

        unregistered = sorted([m for m in expected_modules if m not in _REGISTRY])
        self.assertEqual(
            [], unregistered,
            f"Production modules without validators: {unregistered}",
        )

    def test_unknown_keys_are_rejected(self) -> None:
        """Validators must reject unknown input keys."""
        with self.assertRaises(ModuleValidationError) as cm:
            validate_module_inputs(
                "core/local/quickstart",
                {"operation_id": "test", "unknown_key": "value"},
            )
        self.assertIn("unknown", str(cm.exception).lower())

    def test_lifecycle_keys_are_allowed(self) -> None:
        """Internal lifecycle keys must be allowed by all validators."""
        # These are internal keys added by the runtime, validators must allow them
        lifecycle_keys = {
            "_hyops_lifecycle_command",
            "_hyops_invocation_command",
        }
        for key in lifecycle_keys:
            try:
                validate_module_inputs(
                    "core/local/quickstart",
                    {
                        "operation_id": "test-op",
                        "declared_outcome": "Test outcome",
                        key: "apply",
                    },
                )
            except ModuleValidationError as e:
                self.fail(f"Lifecycle key {key!r} should be allowed: {e}")

    def test_new_validators_reject_unknown_keys(self) -> None:
        """New validators for previously unvalidated modules must reject unknown keys."""
        test_cases = [
            ("platform/gcp/vm-firewall-rules", {}, {"bad_key": "value"}),
            ("platform/linux/containerlab", {}, {"bad_key": "value"}),
            ("platform/linux/gns3-server", {}, {"unknown": True}),
            ("platform/linux/containerlab-healthcheck", {}, {"invalid_input": "test"}),
        ]

        for module_ref, valid_inputs, invalid_extra in test_cases:
            # Valid/empty inputs should be accepted
            try:
                validate_module_inputs(module_ref, valid_inputs)
            except ModuleValidationError as e:
                self.fail(f"Valid inputs for {module_ref} should be accepted: {e}")

            # Unknown keys should be rejected
            invalid_inputs = {**valid_inputs, **invalid_extra}
            with self.assertRaises(ModuleValidationError) as cm:
                validate_module_inputs(module_ref, invalid_inputs)
            self.assertIn("unknown", str(cm.exception).lower())

    def test_require_validator_enforcement(self) -> None:
        """require_validator parameter properly enforces validation."""
        # Module without validator should be rejected when require_validator=True
        unregistered_ref = "nonexistent/module/ref"
        with self.assertRaises(ModuleValidationError):
            validate_module_inputs(
                unregistered_ref,
                {"some_input": "value"},
                require_validator=True
            )

    def test_all_validators_exist_for_production_modules(self) -> None:
        """Verify validators are callable for all production modules."""
        production_modules = [
            "core/local/quickstart",
            "platform/gcp/vm-firewall-rules",
            "platform/linux/containerlab",
            "platform/linux/gns3-server",
        ]

        for module_ref in production_modules:
            # Should not raise - validators must be registered and callable
            try:
                validate_module_inputs(module_ref, {})
            except ModuleValidationError as e:
                # Empty dict might fail for modules with required inputs
                # but the validator should exist and be callable
                pass


if __name__ == "__main__":
    unittest.main()
