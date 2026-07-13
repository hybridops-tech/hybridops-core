"""Tests for optional and strict plugin registration."""

from __future__ import annotations

import io
import os
import unittest
from contextlib import redirect_stderr
from unittest.mock import patch

from hyops import cli


class PluginRegistrationTests(unittest.TestCase):
    def setUp(self) -> None:
        cli._DRIVERS_REGISTERED = False
        cli._VALIDATORS_REGISTERED = False

    def tearDown(self) -> None:
        cli._DRIVERS_REGISTERED = False
        cli._VALIDATORS_REGISTERED = False

    def test_default_mode_warns_for_driver_plugin_failure(self) -> None:
        stderr = io.StringIO()
        with (
            patch.dict(os.environ, {"HYOPS_STRICT_PLUGINS": ""}),
            patch.object(cli, "register_builtin_drivers"),
            patch.object(cli, "register_driver_plugins", side_effect=RuntimeError("broken driver")),
            redirect_stderr(stderr),
        ):
            cli._register_drivers()

        self.assertIn("WARN: driver plugin registration failed: broken driver", stderr.getvalue())
        self.assertTrue(cli._DRIVERS_REGISTERED)

    def test_default_mode_warns_for_validator_plugin_failure(self) -> None:
        stderr = io.StringIO()
        with (
            patch.dict(os.environ, {"HYOPS_STRICT_PLUGINS": ""}),
            patch.object(cli, "register_builtin_validators"),
            patch.object(cli, "register_validator_plugins", side_effect=RuntimeError("broken validator")),
            redirect_stderr(stderr),
        ):
            cli._register_validators()

        self.assertIn("WARN: validator plugin registration failed: broken validator", stderr.getvalue())
        self.assertTrue(cli._VALIDATORS_REGISTERED)

    def test_strict_mode_raises_driver_plugin_failure(self) -> None:
        with (
            patch.dict(os.environ, {"HYOPS_STRICT_PLUGINS": "1"}),
            patch.object(cli, "register_builtin_drivers"),
            patch.object(cli, "register_driver_plugins", side_effect=RuntimeError("broken driver")),
            self.assertRaisesRegex(RuntimeError, "broken driver"),
        ):
            cli._register_drivers()

        self.assertFalse(cli._DRIVERS_REGISTERED)

    def test_strict_mode_raises_validator_plugin_failure(self) -> None:
        with (
            patch.dict(os.environ, {"HYOPS_STRICT_PLUGINS": "1"}),
            patch.object(cli, "register_builtin_validators"),
            patch.object(cli, "register_validator_plugins", side_effect=RuntimeError("broken validator")),
            self.assertRaisesRegex(RuntimeError, "broken validator"),
        ):
            cli._register_validators()

        self.assertFalse(cli._VALIDATORS_REGISTERED)


if __name__ == "__main__":
    unittest.main()
