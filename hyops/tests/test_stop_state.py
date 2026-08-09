"""Tests for the provider-neutral environment stop-state validator."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import yaml

from hyops.state.stop_state import (
    NON_TERMINAL,
    TERMINAL,
    TERMINAL_WITH_RETENTION,
    StopStateManifestError,
    evaluate_stop_state,
)


REPO_ROOT = Path(__file__).resolve().parents[2]


def manifest() -> dict:
    return {
        "schema_version": "1.0",
        "environment": {
            "id": "test-lab",
            "state_timestamp": "2026-07-30T18:00:00Z",
            "resources": [
                {
                    "logical_id": "network",
                    "provider_id": "provider/network/test-lab",
                    "state": "destroyed",
                    "retention_class": "reproducible",
                    "cost_basis": "network control plane",
                    "cost_bearing": False,
                },
                {
                    "logical_id": "host",
                    "provider_id": "provider/instance/test-lab",
                    "state": "destroyed",
                    "retention_class": "preserve",
                    "cost_basis": "compute and storage",
                    "archive_scopes": ["lab_state"],
                },
                {
                    "logical_id": "image_cache",
                    "provider_id": "provider/storage/test-lab",
                    "state": "retained",
                    "retention_class": "retained",
                    "cost_basis": "retained storage",
                    "owner": "platform-team",
                    "review_date": "2026-08-31",
                },
            ],
        },
        "estimate": {
            "currency": "USD",
            "fixed_hourly": "0.42",
            "included": ["host"],
            "excluded": ["image_cache"],
            "pricing_timestamp": "2026-07-30T17:45:00Z",
        },
        "archives": [
            {
                "scope": "lab_state",
                "location": "artifacts/test-lab/lab-state.tar.gz",
                "integrity_value": "sha256:abc123",
                "verification": "passed",
            }
        ],
        "teardown": {
            "started_at": "2026-07-30T17:50:00Z",
            "steps": [
                {"resource": "host", "result": "destroyed"},
                {"resource": "network", "result": "destroyed"},
                {"resource": "image_cache", "result": "retained"},
            ],
        },
    }


class StopStateEvaluationTests(unittest.TestCase):
    def evaluate(self, payload: dict) -> dict:
        return evaluate_stop_state(
            payload,
            verified_at="2026-07-30T18:01:00Z",
        )

    def test_terminal_with_retention(self) -> None:
        result = self.evaluate(manifest())

        self.assertEqual(result["result"], TERMINAL_WITH_RETENTION)
        self.assertEqual(result["resources"]["terminal"], 3)
        self.assertEqual(result["resources"]["unresolved"], 0)
        self.assertEqual(result["estimate"]["coverage_percent"], 50.0)
        self.assertTrue(result["estimate"]["scope_complete"])
        self.assertEqual(result["retained_resources"][0]["owner"], "platform-team")
        self.assertEqual(
            [item["outcome"] for item in result["resource_results"]],
            ["removed", "removed", "retained"],
        )
        self.assertEqual(result["archive_results"][0]["verification"], "passed")
        self.assertEqual(
            result["archive_results"][0]["integrity_value"],
            "sha256:abc123",
        )

    def test_terminal_without_retention(self) -> None:
        payload = manifest()
        payload["environment"]["resources"] = payload["environment"]["resources"][:2]
        payload["estimate"]["excluded"] = []
        payload["teardown"]["steps"] = payload["teardown"]["steps"][:2]

        result = self.evaluate(payload)

        self.assertEqual(result["result"], TERMINAL)
        self.assertEqual(result["estimate"]["coverage_percent"], 100.0)
        self.assertEqual(result["retained_resources"], [])

    def test_active_resource_reports_next_action(self) -> None:
        payload = manifest()
        payload["environment"]["resources"][1]["state"] = "failed"
        payload["teardown"]["steps"][0] = {
            "resource": "host",
            "result": "failed",
            "next_action": "repair provider access and retry teardown",
        }

        result = self.evaluate(payload)

        self.assertEqual(result["result"], NON_TERMINAL)
        self.assertEqual(result["resources"]["terminal"], 2)
        issue = result["unresolved_resources"][0]
        self.assertEqual(issue["logical_id"], "host")
        self.assertEqual(
            issue["next_action"],
            "repair provider access and retry teardown",
        )

    def test_archive_must_be_verified(self) -> None:
        payload = manifest()
        payload["archives"][0]["verification"] = "pending"
        payload["archives"][0]["integrity_value"] = ""

        result = self.evaluate(payload)

        self.assertEqual(result["result"], NON_TERMINAL)
        self.assertFalse(result["checks"]["archives_verified"])
        self.assertEqual(result["archive_failures"][0]["scope"], "lab_state")
        self.assertIn(
            "archive verification is pending",
            result["unresolved_resources"][0]["reason"],
        )

    def test_passed_archive_requires_integrity_record(self) -> None:
        payload = manifest()
        payload["archives"][0]["integrity_value"] = ""

        result = self.evaluate(payload)

        self.assertEqual(result["result"], NON_TERMINAL)
        self.assertIn(
            "missing integrity_value",
            result["archive_failures"][0]["reason"],
        )

    def test_retention_requires_owner_and_valid_review_date(self) -> None:
        payload = manifest()
        payload["environment"]["resources"][2]["owner"] = ""
        payload["environment"]["resources"][2]["review_date"] = "next month"

        result = self.evaluate(payload)

        self.assertEqual(result["result"], NON_TERMINAL)
        self.assertFalse(result["checks"]["retention_accountable"])
        issue = result["unresolved_resources"][0]
        self.assertIn("has no owner", issue["reason"])
        self.assertIn("has no valid review date", issue["reason"])

    def test_unclassified_cost_resource_is_non_terminal(self) -> None:
        payload = manifest()
        payload["estimate"]["excluded"] = []

        result = self.evaluate(payload)

        self.assertEqual(result["result"], NON_TERMINAL)
        self.assertTrue(result["checks"]["resources_terminal"])
        self.assertFalse(result["checks"]["estimate_scope_complete"])
        self.assertEqual(
            result["estimate"]["unclassified_resources"],
            ["image_cache"],
        )
        self.assertEqual(result["unresolved_checks"][0]["check"], "estimate_scope")

    def test_estimate_lists_must_not_overlap(self) -> None:
        payload = manifest()
        payload["estimate"]["included"].append("image_cache")

        with self.assertRaisesRegex(
            StopStateManifestError,
            "estimate.included and estimate.excluded overlap",
        ):
            self.evaluate(payload)

    def test_timestamps_require_a_timezone(self) -> None:
        payload = manifest()
        payload["environment"]["state_timestamp"] = "2026-07-30T18:00:00"

        with self.assertRaisesRegex(StopStateManifestError, "must include a timezone"):
            self.evaluate(payload)

    def test_unsupported_schema_version_is_rejected(self) -> None:
        payload = manifest()
        payload["schema_version"] = "2.0"

        with self.assertRaisesRegex(StopStateManifestError, "unsupported schema_version"):
            self.evaluate(payload)

    def test_current_resource_state_supersedes_stale_failed_step(self) -> None:
        payload = manifest()
        payload["teardown"]["steps"][0]["result"] = "failed"

        result = self.evaluate(payload)

        self.assertEqual(result["result"], TERMINAL_WITH_RETENTION)
        host = next(
            item
            for item in result["resource_results"]
            if item["logical_id"] == "host"
        )
        self.assertEqual(host["state"], "destroyed")
        self.assertEqual(host["teardown_result"], "failed")
        self.assertEqual(host["outcome"], "removed")


class StopStateCommandTests(unittest.TestCase):
    def run_cli(self, *args: str) -> subprocess.CompletedProcess[str]:
        env = os.environ.copy()
        env["PYTHONPATH"] = str(REPO_ROOT)
        return subprocess.run(
            [sys.executable, "-m", "hyops.cli", *args],
            cwd=REPO_ROOT,
            env=env,
            text=True,
            capture_output=True,
            check=False,
        )

    def test_json_result_and_output_file(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            manifest_file = root / "stop-state.yml"
            output_file = root / "result.json"
            manifest_file.write_text(
                yaml.safe_dump(manifest(), sort_keys=False),
                encoding="utf-8",
            )

            completed = self.run_cli(
                "state",
                "verify-stop",
                "--manifest",
                str(manifest_file),
                "--output",
                str(output_file),
                "--json",
            )

            self.assertEqual(completed.returncode, 0, completed.stderr)
            stdout = json.loads(completed.stdout)
            written = json.loads(output_file.read_text(encoding="utf-8"))
            self.assertEqual(stdout["result"], TERMINAL_WITH_RETENTION)
            self.assertEqual(written["result"], TERMINAL_WITH_RETENTION)
            self.assertEqual(output_file.stat().st_mode & 0o777, 0o600)

    def test_non_terminal_result_returns_operator_error(self) -> None:
        payload = manifest()
        payload["environment"]["resources"][1]["state"] = "active"
        with tempfile.TemporaryDirectory() as temp_dir:
            manifest_file = Path(temp_dir) / "stop-state.yml"
            manifest_file.write_text(
                yaml.safe_dump(payload, sort_keys=False),
                encoding="utf-8",
            )

            completed = self.run_cli(
                "state",
                "verify-stop",
                "--manifest",
                str(manifest_file),
            )

            self.assertEqual(completed.returncode, 2)
            self.assertIn("stop_state=non_terminal", completed.stdout)
            self.assertIn("estimate scope:", completed.stdout)
            self.assertIn("next:", completed.stdout)


if __name__ == "__main__":
    unittest.main()
