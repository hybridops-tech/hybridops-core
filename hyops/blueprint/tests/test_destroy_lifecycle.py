from __future__ import annotations

import io
import json
import tempfile
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import patch

from hyops.blueprint.command import (
    _complete_destroy_lifecycle,
    _destroy_lifecycle_snapshot,
    run_destroy,
)
from hyops.runtime.cost import CostEstimate


def _payload() -> dict:
    return {
        "blueprint_ref": "gcp/test@v1",
        "mode": "hybrid",
        "path": "/tmp/blueprint.yml",
        "order": ["vm"],
        "steps": [
            {
                "id": "vm",
                "module_ref": "platform/test/vm",
                "state_instance": "vm",
                "action": "deploy",
                "phase": "bootstrap",
                "optional": False,
            }
        ],
        "policy": {"fail_fast": True},
        "archive_before_destroy": {
            "module_ref": "platform/test/archive",
            "state_instance": "archive",
            "inputs": {},
        },
    }


def _namespace(**overrides):
    values = {
        "execute": True,
        "yes": True,
        "json": False,
        "root": None,
        "env": "test",
        "file": None,
        "archive_before_destroy": False,
        "skip_archive": True,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def _snapshot(*, pricing: bool = True) -> dict:
    return {
        "provider": "gcp",
        "resource_generation_started_at": "2026-08-26T10:00:00Z",
        "observed_at": "2026-08-26T12:00:00Z",
        "duration_seconds": 7_200,
        "estimate": {
            "available": pricing,
            "currency": "USD",
            "fixed_hourly": "0.52" if pricing else None,
            "fixed_total": "1.04" if pricing else None,
            "basis": "public list price" if pricing else "unavailable",
            "classification": (
                "public list-price estimate; not a GCP invoice or billing total"
            ),
        },
    }


class DestroyLifecycleSummaryTest(TestCase):
    def test_snapshot_records_stable_generation_start_and_estimate(self) -> None:
        state = {
            "outputs": {
                "vms": {
                    "lab": {
                        "vm_id": "projects/p/zones/z/instances/lab",
                        "creation_timestamp": "2026-08-26T10:00:00Z",
                    }
                }
            }
        }
        estimate = CostEstimate(
            True,
            hourly=Decimal("0.52"),
            currency="USD",
            basis="public list price",
        )
        observed = datetime(2026, 8, 26, 12, 0, tzinfo=timezone.utc)

        with patch(
            "hyops.blueprint.command._gcp_blueprint_cost_context",
            return_value=(state, "p", "z"),
        ):
            snapshot = _destroy_lifecycle_snapshot(
                _payload(),
                SimpleNamespace(),
                estimate=estimate,
                observed_at=observed,
            )

        self.assertEqual(
            snapshot["resource_generation_started_at"],
            "2026-08-26T10:00:00Z",
        )
        self.assertEqual(snapshot["duration_seconds"], 7_200)
        self.assertEqual(snapshot["estimate"]["fixed_total"], "1.04")

    def test_resource_outcome_controls_only_the_ongoing_rate(self) -> None:
        retained = _complete_destroy_lifecycle(
            _snapshot(),
            archive="not-requested",
            resources="retained",
        )
        released = _complete_destroy_lifecycle(
            _snapshot(),
            archive="verified",
            resources="released",
        )
        unverified = _complete_destroy_lifecycle(
            _snapshot(),
            archive="skipped",
            resources="unverified",
        )

        self.assertEqual(retained["estimate"]["ongoing_hourly"], "0.52")
        self.assertEqual(released["estimate"]["ongoing_hourly"], "0.00")
        self.assertIsNone(unverified["estimate"]["ongoing_hourly"])

    def test_keep_writes_retained_summary(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            paths = SimpleNamespace(
                root=Path(tmp),
                state_dir=Path(tmp) / "state",
                logs_dir=Path(tmp) / "logs",
            )
            stdout = io.StringIO()
            with (
                patch("hyops.blueprint.command._resolve_and_validate", return_value=_payload()),
                patch("hyops.blueprint.command.require_runtime_selection"),
                patch("hyops.blueprint.command.resolve_runtime_paths", return_value=paths),
                patch("hyops.blueprint.command.ensure_layout"),
                patch("hyops.blueprint.command.require_runtime_writable"),
                patch("hyops.blueprint.command._enforce_runtime_blueprint_file_scope"),
                patch("hyops.blueprint.command.module_state_status", return_value="ok"),
                patch("hyops.blueprint.command._destroy_lifecycle_snapshot", return_value=_snapshot()),
                patch("hyops.blueprint.command._select_archive_destroy_mode", return_value="keep"),
                patch("hyops.blueprint.command.sys.stdout", stdout),
            ):
                rc = run_destroy(_namespace(yes=False, skip_archive=False))

            record = json.loads(next(paths.logs_dir.rglob("destroy.json")).read_text())

        self.assertEqual(rc, 0)
        self.assertEqual(record["status"], "retained")
        self.assertEqual(record["lifecycle"]["resources"], "retained")
        self.assertEqual(record["lifecycle"]["estimate"]["ongoing_hourly"], "0.52")
        self.assertIn("resource duration so far: 2h 0m", stdout.getvalue())

    def test_archive_destroy_writes_verified_release_summary(self) -> None:
        record, output, rc = self._run_completed_destroy(archive=True)

        self.assertEqual(rc, 0)
        self.assertEqual(record["lifecycle"]["archive"], "verified")
        self.assertEqual(record["lifecycle"]["resources"], "released")
        self.assertEqual(output["lifecycle"]["estimate"]["ongoing_hourly"], "0.00")

    def test_direct_destroy_records_skipped_archive(self) -> None:
        record, output, rc = self._run_completed_destroy(archive=False)

        self.assertEqual(rc, 0)
        self.assertEqual(record["lifecycle"]["archive"], "skipped")
        self.assertEqual(output["lifecycle"]["archive"], "skipped")

    def test_missing_pricing_does_not_block_release(self) -> None:
        record, output, rc = self._run_completed_destroy(
            archive=False,
            snapshot=_snapshot(pricing=False),
        )

        self.assertEqual(rc, 0)
        self.assertIsNone(record["lifecycle"]["estimate"]["fixed_total"])
        self.assertEqual(output["lifecycle"]["estimate"]["ongoing_hourly"], "0.00")

    def test_failed_teardown_reports_ongoing_cost_as_unverified(self) -> None:
        record, output, rc = self._run_completed_destroy(
            archive=False,
            state_status="ok",
            destroy_rc=2,
            cost_cleared=False,
        )

        self.assertEqual(rc, 2)
        self.assertEqual(record["lifecycle"]["resources"], "unverified")
        self.assertIsNone(output["lifecycle"]["estimate"]["ongoing_hourly"])

    def _run_completed_destroy(
        self,
        *,
        archive: bool,
        snapshot: dict | None = None,
        state_status: str = "destroyed",
        destroy_rc: int = 0,
        cost_cleared: bool = True,
    ) -> tuple[dict, dict, int]:
        with tempfile.TemporaryDirectory() as tmp:
            paths = SimpleNamespace(
                root=Path(tmp),
                state_dir=Path(tmp) / "state",
                logs_dir=Path(tmp) / "logs",
            )
            printed: list[str] = []
            ns = _namespace(
                json=True,
                archive_before_destroy=archive,
                skip_archive=not archive,
            )
            with (
                patch("hyops.blueprint.command._resolve_and_validate", return_value=_payload()),
                patch("hyops.blueprint.command.require_runtime_selection"),
                patch("hyops.blueprint.command.resolve_runtime_paths", return_value=paths),
                patch("hyops.blueprint.command.ensure_layout"),
                patch("hyops.blueprint.command.require_runtime_writable"),
                patch("hyops.blueprint.command._enforce_runtime_blueprint_file_scope"),
                patch("hyops.blueprint.command._destroy_lifecycle_snapshot", return_value=snapshot or _snapshot()),
                patch("hyops.blueprint.command.module_state_status", return_value=state_status),
                patch("hyops.blueprint.command.resolved_step_inputs_file", return_value=None),
                patch("hyops.blueprint.command.run_step_module_command", return_value=destroy_rc),
                patch("hyops.blueprint.command._run_archive_before_destroy", return_value=0),
                patch("hyops.blueprint.command._destroyed_blueprint_cost_cleared", return_value=cost_cleared),
                patch("builtins.print", side_effect=lambda *args, **_kwargs: printed.append(" ".join(map(str, args)))),
            ):
                rc = run_destroy(ns)

            record = json.loads(next(paths.logs_dir.rglob("destroy.json")).read_text())
            output = json.loads(next(item for item in printed if item.startswith("{")))
            self.assertEqual(record["lifecycle"], output["lifecycle"])
            return record, output, rc
