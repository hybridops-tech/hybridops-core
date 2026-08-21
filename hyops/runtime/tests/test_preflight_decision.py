"""Tests for auditable preflight decisions."""

from __future__ import annotations

import json
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import patch

from hyops.commands._apply_execute import run_single
from hyops.runtime.paths import RuntimePaths
from hyops.runtime.preflight_decision import (
    complete_preflight_decision,
    new_preflight_decision,
    validate_preflight_bypass,
)


class PreflightDecisionContractTest(TestCase):
    def test_mutating_bypass_requires_reason(self) -> None:
        with self.assertRaisesRegex(ValueError, "requires --preflight-bypass-reason"):
            validate_preflight_bypass(
                command="apply",
                skip_preflight=True,
                reason=None,
            )

    def test_non_mutating_bypass_remains_available_without_reason(self) -> None:
        self.assertEqual(
            validate_preflight_bypass(
                command="validate",
                skip_preflight=True,
                reason=None,
            ),
            "",
        )

    def test_reason_without_bypass_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "requires --skip-preflight"):
            validate_preflight_bypass(
                command="destroy",
                skip_preflight=False,
                reason="provider incident",
            )

    def test_completed_decision_preserves_original_record_time(self) -> None:
        pending = new_preflight_decision(
            command="deploy",
            skip_preflight=False,
        )
        completed = complete_preflight_decision(pending, passed=True)

        self.assertEqual(completed["status"], "passed")
        self.assertEqual(completed["guarantee"], "established")
        self.assertEqual(completed["recorded_at"], pending["recorded_at"])
        self.assertIn("completed_at", completed)


class ModulePreflightEvidenceTest(TestCase):
    @staticmethod
    def _resolved(root: Path) -> SimpleNamespace:
        return SimpleNamespace(
            module_ref="platform/test/module",
            module_dir=root / "module",
            execution={
                "driver": "test/driver",
                "profile": "default@v1",
                "pack_id": "test-pack@v1",
            },
            spec={
                "execution": {
                    "driver": "test/driver",
                    "profile": "default@v1",
                    "pack_id": "test-pack@v1",
                }
            },
            inputs={},
            required_credentials=[],
            dependencies=[],
            dependency_warnings=[],
            outputs_publish=[],
        )

    def _run(
        self,
        *,
        skip_preflight: bool,
        reason: str = "",
        preflight_ok: bool = True,
        malformed_preflight: bool = False,
    ) -> tuple[int, list[str], dict]:
        temporary = TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        paths = RuntimePaths.from_root(root)
        calls: list[str] = []

        def driver(request):
            command = str(request["command"])
            calls.append(command)
            decision_file = next(root.glob("logs/module/*/*/preflight_decision.json"))
            decision = json.loads(decision_file.read_text(encoding="utf-8"))
            if command == "destroy":
                expected = "bypassed" if skip_preflight else "passed"
                self.assertEqual(decision["status"], expected)
            if command == "preflight" and not preflight_ok:
                return {"status": "error", "error": "readiness check failed"}
            if command == "preflight" and malformed_preflight:
                return None
            return {"status": "ok"}

        with (
            patch(
                "hyops.commands._apply_execute.resolve_module",
                return_value=self._resolved(root),
            ),
            patch("hyops.commands._apply_execute.REGISTRY.validate_execution"),
            patch("hyops.commands._apply_execute.REGISTRY.resolve", return_value=driver),
            patch(
                "hyops.commands._apply_execute.new_run_id",
                return_value="destroy-preflight-test",
            ),
            patch("hyops.commands._apply_execute.stamp_runtime"),
        ):
            rc = run_single(
                paths=paths,
                env_name="test",
                command_name="destroy",
                module_ref_raw="platform/test/module",
                module_root=root / "modules",
                inputs_file=None,
                out_dir=None,
                skip_preflight=skip_preflight,
                preflight_bypass_reason=reason,
                state_instance=None,
            )

        decision_file = next(root.glob("logs/module/*/*/preflight_decision.json"))
        decision = json.loads(decision_file.read_text(encoding="utf-8"))
        meta = json.loads(
            (decision_file.parent / "meta.json").read_text(encoding="utf-8")
        )
        self.assertEqual(meta["preflight"], decision)
        return rc, calls, decision

    def test_checked_mutation_records_passed_preflight_before_driver_execution(self) -> None:
        rc, calls, decision = self._run(skip_preflight=False)

        self.assertEqual(rc, 0)
        self.assertEqual(calls, ["preflight", "destroy"])
        self.assertEqual(decision["decision"], "enforce")
        self.assertEqual(decision["status"], "passed")
        self.assertEqual(decision["guarantee"], "established")

    def test_bypass_is_recorded_with_reason_before_driver_execution(self) -> None:
        rc, calls, decision = self._run(
            skip_preflight=True,
            reason="provider recovery under incident INC-42",
        )

        self.assertEqual(rc, 0)
        self.assertEqual(calls, ["destroy"])
        self.assertEqual(decision["decision"], "bypass")
        self.assertEqual(decision["status"], "bypassed")
        self.assertEqual(decision["guarantee"], "not-established")
        self.assertEqual(decision["decision_source"], "operator-cli")
        self.assertEqual(
            decision["reason"],
            "provider recovery under incident INC-42",
        )

    def test_failed_preflight_records_failed_guarantee_and_prevents_mutation(self) -> None:
        rc, calls, decision = self._run(
            skip_preflight=False,
            preflight_ok=False,
        )

        self.assertEqual(rc, 1)
        self.assertEqual(calls, ["preflight"])
        self.assertEqual(decision["status"], "failed")
        self.assertEqual(decision["guarantee"], "not-established")
        self.assertEqual(decision["detail"], "readiness check failed")

    def test_malformed_preflight_result_is_recorded_as_failed(self) -> None:
        rc, calls, decision = self._run(
            skip_preflight=False,
            malformed_preflight=True,
        )

        self.assertEqual(rc, 1)
        self.assertEqual(calls, ["preflight"])
        self.assertEqual(decision["status"], "failed")
        self.assertEqual(decision["guarantee"], "not-established")
        self.assertEqual(
            decision["detail"],
            "driver preflight returned a non-object result",
        )

    def test_direct_mutating_bypass_without_reason_is_rejected(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            rc = run_single(
                paths=RuntimePaths.from_root(root),
                env_name="test",
                command_name="destroy",
                module_ref_raw="platform/test/module",
                module_root=root / "modules",
                inputs_file=None,
                out_dir=None,
                skip_preflight=True,
                state_instance=None,
            )

        self.assertEqual(rc, 2)
