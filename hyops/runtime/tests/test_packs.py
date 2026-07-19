"""Pack root resolution contracts."""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from hyops.runtime.packs import PackNotFoundError, resolve_packs_root


class PackRootResolutionTests(unittest.TestCase):
    def test_explicit_root_keeps_highest_precedence(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            explicit = root / "explicit"
            environment = root / "environment"
            core = root / "core"
            for path in (explicit, environment, core / "packs"):
                path.mkdir(parents=True)

            with patch.dict(
                os.environ,
                {
                    "HYOPS_PACKS_ROOT": str(environment),
                    "HYOPS_CORE_ROOT": str(core),
                },
            ):
                self.assertEqual(resolve_packs_root(str(explicit)), explicit.resolve())

    def test_installed_venv_finds_sibling_app_packs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            install_root = Path(tmp) / "core"
            venv = install_root / "venv"
            packs = install_root / "app" / "packs"
            venv.mkdir(parents=True)
            packs.mkdir(parents=True)

            with (
                patch.dict(
                    os.environ,
                    {"HYOPS_PACKS_ROOT": "", "HYOPS_CORE_ROOT": ""},
                ),
                patch("hyops.runtime.packs.sys.prefix", str(venv)),
                patch("hyops.runtime.packs._find_packs_root_from_here", return_value=None),
            ):
                self.assertEqual(resolve_packs_root(), packs.resolve())

    def test_invalid_explicit_root_does_not_fall_back(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            missing = Path(tmp) / "missing"

            with self.assertRaisesRegex(PackNotFoundError, "packs root not found"):
                resolve_packs_root(str(missing))


if __name__ == "__main__":
    unittest.main()
