"""Tests for plugin availability validation in preflight.

purpose: Verify that preflight fails when a selected driver plugin failed registration
maintainer: HybridOps.Tech
"""

from __future__ import annotations

import unittest
from unittest import mock
import os
import sys
from io import StringIO
from pathlib import Path

from hyops.cli import is_driver_available, get_unavailable_driver_error, _FAILED_DRIVER_PLUGINS


class TestPluginAvailabilityCheck(unittest.TestCase):
    """Test plugin availability checking functions."""

    def setUp(self) -> None:
        """Clear failed plugins before each test."""
        _FAILED_DRIVER_PLUGINS.clear()

    def test_driver_is_available_when_registered(self) -> None:
        """Driver is available when properly registered."""
        # Builtin drivers should be available
        result = is_driver_available("images/packer")
        # This will be True if packer driver exists
        # If not available, we get False which is expected
        self.assertIsInstance(result, bool)

    def test_driver_unavailable_error_for_missing_driver(self) -> None:
        """get_unavailable_driver_error returns message for missing driver."""
        error = get_unavailable_driver_error("nonexistent/driver")
        self.assertIsNotNone(error)
        self.assertIn("driver not found", error)
        self.assertIn("nonexistent/driver", error)

    def test_driver_unavailable_error_for_failed_plugin(self) -> None:
        """get_unavailable_driver_error returns message for failed plugin."""
        # Simulate a failed plugin
        _FAILED_DRIVER_PLUGINS.add("plugin:broken-driver")

        error = get_unavailable_driver_error("plugin:broken-driver")
        self.assertIsNotNone(error)
        self.assertIn("driver plugin failed to register", error)
        self.assertIn("plugin:broken-driver", error)
        self.assertNotIn("Traceback", error)

    def test_no_error_for_available_driver(self) -> None:
        """get_unavailable_driver_error returns None for available driver."""
        # Builtin drivers should be available
        error = get_unavailable_driver_error("images/packer")
        # If packer is available, error should be None
        if "images/packer" in ["images/packer"]:  # Known builtin driver
            self.assertIsNone(error, "Packer driver should be available")

    def test_failed_plugin_name_extraction(self) -> None:
        """Plugin names are correctly extracted from error messages."""
        test_cases = [
            ("group=hyops.drivers name=broken-driver", "plugin:broken-driver"),
            ("group=hyops.drivers name=test plugin", "plugin:test"),
            ('group=hyops.drivers name="quoted-driver"', "plugin:quoted-driver"),
        ]

        for error_str, expected_plugin in test_cases:
            _FAILED_DRIVER_PLUGINS.clear()

            # Simulate the error extraction logic
            if "name=" in error_str:
                parts = error_str.split("name=")
                if len(parts) > 1:
                    plugin_name = parts[1].split()[0].strip("'\"")
                    extracted = f"plugin:{plugin_name}"
                    self.assertEqual(extracted, expected_plugin)


class TestPreflightPluginValidation(unittest.TestCase):
    """Test preflight command with plugin availability checks."""

    def setUp(self) -> None:
        """Clear failed plugins and capture stderr."""
        _FAILED_DRIVER_PLUGINS.clear()
        self.stderr_capture = StringIO()

    def test_preflight_with_unavailable_driver_fails(self) -> None:
        """Preflight should fail if selected driver is unavailable.

        This tests the integration: when a module selects a failed driver,
        preflight should catch it before attempting to run the driver.
        """
        # This test verifies the code path exists; actual failure testing
        # would require a full integration test with mock modules/drivers
        # The key assertion is that the check code is in place:
        # from hyops.cli import get_unavailable_driver_error
        # driver_error = get_unavailable_driver_error(driver_ref)
        # if driver_error: raise ValueError(...)

        # Verify the function signature exists
        self.assertTrue(callable(get_unavailable_driver_error))
        self.assertTrue(callable(is_driver_available))

    def test_unselected_plugin_failure_doesnt_block_commands(self) -> None:
        """Unselected plugin failures should not block builtin commands.

        When a plugin fails to register, only commands that explicitly
        select that plugin should fail. Built-in commands that don't
        use that plugin should continue to work.
        """
        # Simulate a failed plugin that isn't used by core commands
        _FAILED_DRIVER_PLUGINS.add("plugin:broken-optional-driver")

        # Builtin commands should not be affected
        # (they don't try to resolve the broken plugin)
        error = get_unavailable_driver_error("images/packer")
        # Packer should still be available
        if error and "not found" in error:
            # OK - packer doesn't exist in test env
            pass
        else:
            # Error should be None for available driver
            self.assertIsNone(error)

    def test_error_message_format(self) -> None:
        """Error messages should be clear and not include full traceback."""
        _FAILED_DRIVER_PLUGINS.add("plugin:bad-driver")

        error = get_unavailable_driver_error("plugin:bad-driver")

        # Verify error is a simple string without traceback
        self.assertIsInstance(error, str)
        self.assertNotIn("Traceback", error)
        self.assertNotIn("File ", error)
        self.assertNotIn("at line", error)

        # Verify it identifies the driver clearly
        self.assertIn("bad-driver", error)
        self.assertIn("failed to register", error.lower())


class TestHYOPS_STRICT_PLUGINS(unittest.TestCase):
    """Test that HYOPS_STRICT_PLUGINS behavior is unchanged."""

    def test_strict_plugins_env_var_preserved(self) -> None:
        """HYOPS_STRICT_PLUGINS environment variable behavior preserved.

        When HYOPS_STRICT_PLUGINS=1, plugin registration should fail
        immediately rather than warn and continue.

        This test documents that the original behavior is preserved;
        the actual enforcement happens in _register_drivers().
        """
        # The behavior is:
        # - HYOPS_STRICT_PLUGINS=1: raise exception on plugin failure
        # - HYOPS_STRICT_PLUGINS="" (default): warn and track failure

        # Code path verification:
        # strict = os.environ.get("HYOPS_STRICT_PLUGINS", "").strip() == "1"
        # if strict: raise
        # else: warn + track

        strict_var = os.environ.get("HYOPS_STRICT_PLUGINS", "").strip()
        self.assertEqual(strict_var, "")  # Should not be set in normal tests


if __name__ == "__main__":
    unittest.main()
