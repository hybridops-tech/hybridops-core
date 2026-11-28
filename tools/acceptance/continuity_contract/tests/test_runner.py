from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tools.acceptance.continuity_contract import runner


class ContinuityContractAcceptanceTests(unittest.TestCase):
    def test_release_and_producer_evidence_paths(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "acceptance"

            report = runner.run(output)

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

            produced = report["scenarios"]["producer-only"]
            omitted = report["scenarios"]["producer-omitted"]
            prepare_calls = [["admit", "prepare"], ["execute", "prepare"]]
            self.assertEqual(produced["calls"], prepare_calls)
            self.assertEqual(omitted["calls"], [*prepare_calls, ["recover", "prepare"]])
            failed = json.loads(Path(omitted["terminal"]).read_text(encoding="utf-8"))
            self.assertEqual(failed["reason_code"], "missing_producer_evidence")

    def test_wrong_producer_terminal_reason_fails_standalone_report(self) -> None:
        publish = runner.FileOperationStore.publish

        def wrong_reason(store, lease, record):
            if record["reason_code"] == "missing_producer_evidence":
                record = {**record, "reason_code": "unrelated_failure"}
            return publish(store, lease, record)

        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "acceptance"
            with patch.object(runner.FileOperationStore, "publish", wrong_reason):
                runner.run(output)
            report = json.loads((output / "report.json").read_text(encoding="utf-8"))
            scenario = report["scenarios"]["producer-omitted"]
            self.assertEqual(report["status"], "failed")
            self.assertFalse(scenario["checks"]["terminal_reason"])
            self.assertTrue(scenario["checks"]["producer_failure"])

    def test_missing_producer_artifact_is_reported(self) -> None:
        execute = runner._LocalAdapter.execute

        def remove_artifact(adapter, request):
            result = execute(adapter, request)
            if request.operation_id == "producer-only":
                Path(result.outputs["artifact"]).unlink()
            return result

        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "acceptance"
            with patch.object(runner._LocalAdapter, "execute", remove_artifact):
                runner.run(output)
            report = json.loads((output / "report.json").read_text(encoding="utf-8"))
            scenario = report["scenarios"]["producer-only"]
            self.assertEqual(report["status"], "failed")
            self.assertFalse(scenario["checks"]["content_identity"])
            self.assertTrue(scenario["checks"]["terminal_status"])


if __name__ == "__main__":
    unittest.main()
