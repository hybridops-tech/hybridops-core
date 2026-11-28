from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from tools.acceptance.continuity_contract.runner import run


class ContinuityContractAcceptanceTests(unittest.TestCase):
    def test_completed_and_denied_release_paths(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "acceptance"

            report = run(output)

            self.assertEqual(report["status"], "passed")
            completed = report["scenarios"]["completed"]
            denied = report["scenarios"]["release-denied"]
            self.assertEqual(completed["status"], "passed")
            self.assertEqual(denied["status"], "passed")
            self.assertTrue(all(completed["checks"].values()))
            self.assertTrue(all(denied["checks"].values()))
            self.assertEqual(
                completed["calls"],
                [
                    ["admit", "prepare"],
                    ["execute", "prepare"],
                    ["admit", "release"],
                    ["execute", "release"],
                ],
            )
            self.assertEqual(
                denied["calls"],
                [
                    ["admit", "prepare"],
                    ["execute", "prepare"],
                    ["admit", "release"],
                    ["recover", "prepare"],
                ],
            )
            self.assertTrue((output / "report.json").is_file())
            terminal_path = Path(completed["terminal"])
            terminal = json.loads(terminal_path.read_text(encoding="utf-8"))
            denied_terminal = json.loads(
                Path(denied["terminal"]).read_text(encoding="utf-8")
            )
            self.assertEqual(terminal["status"], "succeeded")
            self.assertEqual(terminal["closure"], "completed")
            self.assertEqual(terminal["reason_code"], "")
            self.assertEqual(denied_terminal["status"], "recovered")
            self.assertEqual(denied_terminal["closure"], "recovered")
            self.assertEqual(
                denied_terminal["reason_code"],
                "adapter_admission_denied",
            )
            self.assertTrue(terminal["contract"]["digest"].startswith("sha256:"))
            self.assertTrue(terminal["controller"]["revision"].startswith("sha256:"))
            self.assertEqual(
                terminal["stages"][0]["evidence"][0]["role"],
                "recovery_set",
            )
            self.assertEqual(
                len(list((output / "completed" / "operations").glob("*.json"))),
                0,
            )
            self.assertEqual(
                len(list((output / "completed" / "operations").glob("*/claim.json"))),
                1,
            )


if __name__ == "__main__":
    unittest.main()
