"""Regression tests for offline blueprint inspection."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]
BLUEPRINT_REF = "onprem/authoritative-foundation@v1"


def _run(command: str) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["PYTHONPATH"] = str(REPO_ROOT)
    env["PYTHONIOENCODING"] = "utf-8"
    env.pop("HYOPS_ENV", None)
    env.pop("HYOPS_RUNTIME_ROOT", None)
    with tempfile.TemporaryDirectory() as home:
        env["HOME"] = home
        return subprocess.run(
            [
                sys.executable,
                "-m",
                "hyops.cli",
                "blueprint",
                command,
                "--ref",
                BLUEPRINT_REF,
                "--json",
            ],
            cwd=REPO_ROOT,
            env=env,
            text=True,
            capture_output=True,
            stdin=subprocess.DEVNULL,
            check=False,
        )


class OfflineBlueprintInspectionTests(unittest.TestCase):
    def test_validate_and_plan_do_not_ask_for_runtime_state(self) -> None:
        plan_payload = None
        for command in ("validate", "plan"):
            with self.subTest(command=command):
                result = _run(command)
                rendered = result.stdout + result.stderr
                self.assertEqual(result.returncode, 0, rendered)
                payload = json.loads(result.stdout)
                self.assertEqual(payload["blueprint_ref"], BLUEPRINT_REF)
                self.assertNotIn("requires explicit runtime selection", rendered)
                if command == "plan":
                    plan_payload = payload

        self.assertIsNotNone(plan_payload)
        assert plan_payload is not None
        self.assertGreaterEqual(len(plan_payload["order"]), 1)
        self.assertEqual(plan_payload["order"][0], "network_sdn")
        self.assertIn("steps", plan_payload)


if __name__ == "__main__":
    unittest.main()
