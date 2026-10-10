"""Tests for selected driver readiness after plugin registration failure."""

from __future__ import annotations

import io
import json
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch

from hyops.commands._apply_execute import run_single
from hyops.drivers.registry import DriverRegistry
from hyops.preflight.command import run as run_preflight
from hyops.runtime.exitcodes import DEPENDENCY_MISSING, OK


def _failed_registry() -> DriverRegistry:
    registry = DriverRegistry()
    try:
        with registry.plugin_registration("broken-plugin"):
            raise ModuleNotFoundError("missing plugin dependency")
    except ModuleNotFoundError:
        pass
    return registry


def _resolved(driver: str):
    return SimpleNamespace(
        module_ref="platform/test/module",
        module_dir=Path("/tmp/module"),
        spec={
            "execution": {
                "driver": driver,
                "profile": "default@v1",
                "pack_ref": {"id": "test/pack@v1"},
            }
        },
        execution={
            "driver": driver,
            "profile": "default@v1",
            "pack_id": "test/pack@v1",
            "hooks": {},
        },
        inputs={},
        required_credentials=[],
        dependencies=[],
        dependency_warnings=[],
        outputs_publish=[],
    )


def _preflight_namespace(root: Path):
    return SimpleNamespace(
        root=str(root),
        env=None,
        target=None,
        json=True,
        strict=False,
        vault_file=None,
        vault_password_file=None,
        vault_password_command=None,
        module="platform/test/module",
        module_root="modules",
        inputs=None,
        state_instance=None,
    )


class SelectedPluginReadinessTests(unittest.TestCase):
    def test_selected_failed_plugin_returns_dependency_error(self) -> None:
        registry = _failed_registry()
        stdout = io.StringIO()

        with TemporaryDirectory() as tmp:
            with (
                patch("hyops.preflight.command.REGISTRY", registry),
                patch(
                    "hyops.preflight.command.resolve_module",
                    return_value=_resolved("third-party/broken"),
                ),
                redirect_stdout(stdout),
            ):
                result = run_preflight(_preflight_namespace(Path(tmp)))

        payload = json.loads(stdout.getvalue())
        self.assertEqual(result, DEPENDENCY_MISSING)
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["code"], DEPENDENCY_MISSING)
        self.assertIn("driver unavailable: third-party/broken", payload["module_preflight"]["error"])
        self.assertNotIn("Traceback", stdout.getvalue())

    def test_unselected_plugin_failure_does_not_block_builtin_driver(self) -> None:
        registry = _failed_registry()
        registry.register(
            "builtin/test",
            lambda request: {"status": "ok"},
            source="builtin",
        )
        stdout = io.StringIO()

        with TemporaryDirectory() as tmp:
            with (
                patch("hyops.preflight.command.REGISTRY", registry),
                patch(
                    "hyops.preflight.command.resolve_module",
                    return_value=_resolved("builtin/test"),
                ),
                redirect_stdout(stdout),
            ):
                result = run_preflight(_preflight_namespace(Path(tmp)))

        payload = json.loads(stdout.getvalue())
        self.assertEqual(result, OK)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["module_preflight"]["status"], "ok")

    def test_apply_stops_before_selected_failed_driver_execution(self) -> None:
        registry = _failed_registry()
        stderr = io.StringIO()

        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            paths = SimpleNamespace(
                root=root,
                state_dir=root / "state",
                logs_dir=root / "logs",
                meta_dir=root / "meta",
                credentials_dir=root / "credentials",
                work_dir=root / "work",
            )
            with (
                patch("hyops.commands._apply_execute.REGISTRY", registry),
                patch(
                    "hyops.commands._apply_execute.resolve_module",
                    return_value=_resolved("third-party/broken"),
                ),
                patch("hyops.commands._apply_execute.init_evidence_dir") as evidence,
                redirect_stderr(stderr),
            ):
                result = run_single(
                    paths=paths,
                    env_name="test",
                    command_name="apply",
                    module_ref_raw="platform/test/module",
                    module_root=root / "modules",
                    inputs_file=None,
                    out_dir=None,
                    skip_preflight=False,
                    state_instance=None,
                )

        self.assertEqual(result, 1)
        self.assertIn("driver unavailable: third-party/broken", stderr.getvalue())
        evidence.assert_not_called()


if __name__ == "__main__":
    unittest.main()
