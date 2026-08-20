"""Tests for `hyops blueprint edit`."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import patch

from hyops.blueprint.command import _editor_argv, _resolve_edit_target, run_edit
from hyops.runtime.exitcodes import OPERATOR_ERROR


class BlueprintEditTests(TestCase):
    def test_editor_argv_uses_cli_override(self) -> None:
        ns = SimpleNamespace(editor="cat", file="", ref="", root="", env="")
        argv = _editor_argv(ns)
        self.assertEqual(argv, ["cat"])

    def test_resolve_edit_target_requires_init_when_no_explicit_file(self) -> None:
        with tempfile.TemporaryDirectory() as root_dir:
            ns = SimpleNamespace(root=root_dir, env=None, ref="gcp/eve-ng@v1", file="", editor="")
            with self.assertRaises(FileNotFoundError):
                _resolve_edit_target(ns)

    def test_resolve_edit_target_uses_explicit_file_under_runtime(self) -> None:
        with tempfile.TemporaryDirectory() as root_dir:
            config_dir = Path(root_dir) / "config" / "blueprints"
            config_dir.mkdir(parents=True)
            explicit = config_dir / "custom.yml"
            explicit.write_text("blueprint_ref: gcp/eve-ng@v1\n", encoding="utf-8")

            ns = SimpleNamespace(root=root_dir, env=None, ref="", file=str(explicit), editor="")
            resolved = _resolve_edit_target(ns)
            self.assertEqual(resolved, explicit)

    def test_run_edit_invokes_editor(self) -> None:
        with tempfile.TemporaryDirectory() as root_dir:
            config_dir = Path(root_dir) / "config" / "blueprints"
            config_dir.mkdir(parents=True)
            blueprint = config_dir / "eve-ng.yml"
            blueprint.write_text("blueprint_ref: gcp/eve-ng@v1\n", encoding="utf-8")

            ns = SimpleNamespace(
                root=root_dir,
                env=None,
                ref="gcp/eve-ng@v1",
                file="",
                editor="",
            )

            with patch("hyops.blueprint.command.subprocess.run") as run:
                run.return_value.returncode = 0
                rc = run_edit(ns)
                self.assertEqual(rc, 0)
                run.assert_called_once()

    def test_run_edit_fails_when_editor_missing(self) -> None:
        ns = SimpleNamespace(root="", env="", ref="", file="", editor="")
        with tempfile.TemporaryDirectory() as root_dir:
            ns.root = root_dir
            config_dir = Path(root_dir) / "config" / "blueprints"
            config_dir.mkdir(parents=True)
            blueprint = config_dir / "custom.yml"
            blueprint.write_text("blueprint_ref: gcp/eve-ng@v1\n", encoding="utf-8")
            ns.file = str(blueprint)

            with patch.dict(os.environ, {"PATH": ""}, clear=True):
                with patch("hyops.blueprint.command.shutil.which", return_value=None) as which:
                    rc = run_edit(ns)
                    self.assertEqual(rc, OPERATOR_ERROR)
                    which.assert_called()


if __name__ == "__main__":
    import unittest

    unittest.main()
