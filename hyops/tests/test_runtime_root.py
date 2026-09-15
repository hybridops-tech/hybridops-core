"""Tests for explicit CLI and environment runtime-root precedence."""

from __future__ import annotations

import os
import unittest
from pathlib import Path
from unittest.mock import patch

from hyops.runtime.root import resolve_runtime_root


class RuntimeRootTests(unittest.TestCase):
    def test_selection_precedence(self) -> None:
        home = Path.home()
        cli_root = home / "cli-runtime"
        runtime_root = home / "shared-runtime"
        default_root = home / ".hybridops"
        cases = (
            (str(cli_root), None, str(runtime_root), "staging", cli_root),
            (str(cli_root), None, "", "staging", cli_root),
            (None, "production", str(runtime_root), "staging", default_root / "envs" / "production"),
            (None, "production", str(runtime_root), "", default_root / "envs" / "production"),
            (None, "production", "", "staging", default_root / "envs" / "production"),
            (None, "production", "", "", default_root / "envs" / "production"),
            (None, None, str(runtime_root), "staging", runtime_root),
            (None, None, str(runtime_root), "", runtime_root),
            (None, None, "", "staging", default_root / "envs" / "staging"),
            (None, None, "", "", default_root),
        )
        for ns_root, ns_env, runtime_env, env_name, expected in cases:
            with self.subTest(root=ns_root, env=ns_env, runtime_env=runtime_env, env_name=env_name):
                with patch.dict(os.environ, {"HYOPS_RUNTIME_ROOT": runtime_env, "HYOPS_ENV": env_name}):
                    self.assertEqual(resolve_runtime_root(ns_root, ns_env), expected.resolve())

    def test_root_and_env_remain_mutually_exclusive(self) -> None:
        with patch.dict(os.environ, {"HYOPS_RUNTIME_ROOT": "shared-runtime", "HYOPS_ENV": "staging"}):
            with self.assertRaisesRegex(ValueError, "--root and --env are mutually exclusive"):
                resolve_runtime_root("cli-runtime", "production")

    def test_explicit_env_is_validated_even_with_runtime_root(self) -> None:
        with patch.dict(os.environ, {"HYOPS_RUNTIME_ROOT": "shared-runtime", "HYOPS_ENV": "staging"}):
            for env_name in ("../production", "production/test", "production\\test", "invalid name"):
                with self.subTest(env=env_name):
                    with self.assertRaisesRegex(ValueError, "invalid env name"):
                        resolve_runtime_root(None, env_name)
