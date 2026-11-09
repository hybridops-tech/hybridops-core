"""Tests for optional and strict plugin registration."""

from __future__ import annotations

import io
import os
import unittest
from contextlib import redirect_stderr
from unittest.mock import patch

from hyops import cli
from hyops.drivers.plugins import register_plugins
from hyops.drivers.registry import DriverRegistry, DriverUnavailableError


class _EntryPoints(list):
    def select(self, *, group: str):
        return self if group == "hyops.drivers" else []


class _EntryPoint:
    group = "hyops.drivers"

    def __init__(self, name: str, hook) -> None:
        self.name = name
        self._hook = hook

    def load(self):
        return self._hook


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

    def test_failed_plugin_registration_is_rolled_back(self) -> None:
        registry = DriverRegistry()

        def builtin_driver(request):
            return {"status": "ok"}

        def broken_hook(target: DriverRegistry) -> None:
            target.register(
                "third-party/broken",
                lambda request: {"status": "ok"},
                source="plugin:broken-plugin",
            )
            raise ModuleNotFoundError("missing plugin dependency")

        registry.register("builtin/test", builtin_driver, source="builtin")
        entry_points = _EntryPoints([_EntryPoint("broken-plugin", broken_hook)])

        with (
            patch("importlib.metadata.entry_points", return_value=entry_points),
            self.assertRaisesRegex(RuntimeError, "driver plugin hook failed"),
        ):
            register_plugins(registry)

        self.assertIs(registry.resolve("builtin/test"), builtin_driver)
        with self.assertRaisesRegex(
            DriverUnavailableError,
            r"driver unavailable: third-party/broken .*broken-plugin",
        ):
            registry.resolve("third-party/broken")

    def test_load_failure_marks_selected_driver_unavailable(self) -> None:
        registry = DriverRegistry()
        entry_point = _EntryPoint("missing-plugin", None)

        with (
            patch.object(
                entry_point,
                "load",
                side_effect=ModuleNotFoundError("missing plugin dependency"),
            ),
            patch(
                "importlib.metadata.entry_points",
                return_value=_EntryPoints([entry_point]),
            ),
            self.assertRaisesRegex(ModuleNotFoundError, "missing plugin dependency"),
        ):
            register_plugins(registry)

        with self.assertRaisesRegex(
            DriverUnavailableError,
            r"driver unavailable: third-party/missing .*missing-plugin",
        ):
            registry.resolve("third-party/missing")


if __name__ == "__main__":
    unittest.main()
