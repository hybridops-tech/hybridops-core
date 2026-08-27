from __future__ import annotations

import io
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from hyops.runtime.exitcodes import CONFIG_INVALID
from hyops.secrets.command import run_ensure


class EnsureSecretsTests(unittest.TestCase):
    def test_rejects_generation_of_file_backed_secret(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            paths = SimpleNamespace(root=root, vault_dir=root, state_dir=root)
            ns = SimpleNamespace(
                env="lab",
                vault_file=None,
                vault_password_file=None,
                vault_password_command=None,
                keys=["EVENG_IOL_LICENSE"],
                module=None,
                length_map=[],
                length=None,
                force=False,
                dry_run=False,
                persist=None,
            )

            output = io.StringIO()
            with (
                patch("hyops.secrets.command._resolve_paths", return_value=(paths, None)),
                patch("hyops.secrets.command.shutil.which", return_value="/usr/bin/ansible-vault"),
                redirect_stdout(output),
            ):
                result = run_ensure(ns)

        self.assertEqual(result, CONFIG_INVALID)
        self.assertIn("EVENG_IOL_LICENSE cannot be generated", output.getvalue())
        self.assertIn("--from-file EVENG_IOL_LICENSE=/path/to/iourc", output.getvalue())


if __name__ == "__main__":
    unittest.main()
