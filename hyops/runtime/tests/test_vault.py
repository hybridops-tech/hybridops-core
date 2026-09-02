from __future__ import annotations

import os
from pathlib import Path
import unittest
from unittest.mock import patch

from hyops.runtime.vault import VaultAuth, _parse_env


class VaultEnvParsingTest(unittest.TestCase):
    def test_parses_escaped_and_legacy_multiline_values(self) -> None:
        parsed = _parse_env(
            """\
SIMPLE=value
ESCAPED="line-one\\nline-two"
LEGACY_JSON="{\n  \\"private_key\\": \\"first=second\\nthird\\"\n}"
"""
        )

        self.assertEqual(parsed["SIMPLE"], "value")
        self.assertEqual(parsed["ESCAPED"], "line-one\nline-two")
        self.assertEqual(
            parsed["LEGACY_JSON"],
            '{\n  "private_key": "first=second\nthird"\n}',
        )
        self.assertEqual(set(parsed), {"SIMPLE", "ESCAPED", "LEGACY_JSON"})

    def test_ignores_non_environment_assignment_fragments(self) -> None:
        parsed = _parse_env(
            'SAFE=value\n"private_key": "base64=fragment"\ninvalid-name=value\n'
        )

        self.assertEqual(parsed, {"SAFE": "value"})

    def test_rejects_unterminated_quoted_value(self) -> None:
        with self.assertRaisesRegex(ValueError, "unterminated quoted value for SECRET"):
            _parse_env('SECRET="unfinished\n')


class VaultAuthTest(unittest.TestCase):
    def test_owns_materialized_password_file_outside_system_tmp(self) -> None:
        auth = VaultAuth(password_command="password-command")

        self.assertTrue(
            auth.owns_password_file(Path("/workspace/tmp/hyops.vaultpass.example"))
        )

    def test_does_not_own_explicit_password_file(self) -> None:
        auth = VaultAuth(password_file="/workspace/tmp/hyops.vaultpass.explicit")

        self.assertFalse(
            auth.owns_password_file(Path("/workspace/tmp/hyops.vaultpass.explicit"))
        )

    def test_does_not_own_password_file_from_environment(self) -> None:
        auth = VaultAuth(password_command="password-command")
        with patch.dict(
            os.environ,
            {"HYOPS_VAULT_PASSWORD_FILE": "/workspace/password-file"},
            clear=False,
        ):
            self.assertFalse(
                auth.owns_password_file(Path("/workspace/tmp/hyops.vaultpass.example"))
            )


if __name__ == "__main__":
    unittest.main()
