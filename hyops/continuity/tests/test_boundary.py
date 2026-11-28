from __future__ import annotations

import importlib.util
import sys
import tempfile
import unittest
from contextlib import redirect_stderr
from io import StringIO
from pathlib import Path
from unittest.mock import patch


class ContinuityBoundaryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        repo_root = Path(__file__).resolve().parents[3]
        cls.checker_path = repo_root / "tools" / "ci" / "check-continuity-boundary.py"
        spec = importlib.util.spec_from_file_location(
            "check_continuity_boundary",
            cls.checker_path,
        )
        assert spec is not None and spec.loader is not None
        cls.checker = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.checker)

    def _run_checker(
        self,
        kernel_source: str,
        authority_source: str = "",
        *,
        authority_init_source: str = "",
    ) -> str:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            hyops = root / "hyops"
            hyops.mkdir()
            (hyops / "__init__.py").write_text("", encoding="utf-8")
            kernel = root / "hyops" / "continuity"
            kernel.mkdir(parents=True)
            (kernel / "__init__.py").write_text(
                "from .escape import *\n",
                encoding="utf-8",
            )
            authority = root / "hyops" / "authority"
            authority.mkdir(parents=True)
            (authority / "__init__.py").write_text(
                authority_init_source,
                encoding="utf-8",
            )
            (authority / "models.py").write_text(authority_source, encoding="utf-8")
            (kernel / "escape.py").write_text(kernel_source, encoding="utf-8")
            stderr = StringIO()
            with (
                patch.object(sys, "argv", [str(self.checker_path), str(root)]),
                redirect_stderr(stderr),
            ):
                result = self.checker.main()

        self.assertEqual(result, 1)
        return stderr.getvalue()

    def test_relative_import_cannot_escape_kernel(self) -> None:
        error = self._run_checker("from ..drivers import registry\n")

        self.assertIn("hyops.drivers", error)

    def test_allowed_dependency_cannot_hide_transitive_import(self) -> None:
        error = self._run_checker(
            "from hyops.authority.models import AuthorityContext\n",
            "from hyops.drivers import registry\n",
        )

        self.assertIn("hyops.drivers", error)

    def test_allowed_dependency_package_initializer_cannot_escape(self) -> None:
        error = self._run_checker(
            "from hyops.authority.models import AuthorityContext\n",
            "class AuthorityContext:\n    pass\n",
            authority_init_source="from hyops.drivers import registry\n",
        )

        self.assertIn("hyops.drivers", error)

    def test_undeclared_external_import_is_rejected(self) -> None:
        error = self._run_checker("import requests\n")

        self.assertIn("disallowed external module requests", error)

    def test_dynamic_loader_import_is_rejected(self) -> None:
        error = self._run_checker(
            "import importlib\nimportlib.import_module('hyops.drivers')\n"
        )

        self.assertIn("disallowed dynamic loader importlib", error)
        self.assertIn("calls disallowed dynamic loader import_module", error)

    def test_builtin_dynamic_import_call_is_rejected(self) -> None:
        error = self._run_checker("__import__('hyops.drivers')\n")

        self.assertIn("calls disallowed dynamic loader __import__", error)


if __name__ == "__main__":
    unittest.main()
