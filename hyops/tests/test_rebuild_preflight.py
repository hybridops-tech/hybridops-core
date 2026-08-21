"""Tests for rebuild preflight evidence."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch

from hyops.commands.rebuild import run
from hyops.runtime.paths import RuntimePaths


def _namespace(root: Path, *, skip_preflight: bool, reason: str | None) -> argparse.Namespace:
    return argparse.Namespace(
        root=str(root),
        env=None,
        module="platform/test/module",
        module_root="modules",
        inputs=None,
        out_dir=None,
        skip_preflight=skip_preflight,
        preflight_bypass_reason=reason,
        yes=True,
        confirm_module=None,
        with_deps=False,
        deps_inputs_dir=None,
        deps_force=False,
    )


class RebuildPreflightEvidenceTest(TestCase):
    def _run(
        self,
        *,
        skip_preflight: bool,
        reason: str | None,
    ) -> tuple[int, list[dict], dict]:
        temporary = TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        paths = RuntimePaths.from_root(root)
        observed: list[dict] = []

        def run_phase(_ns):
            decision_path = (
                root
                / "logs/rebuild/platform__test__module/rebuild-test"
                / "preflight_decision.json"
            )
            observed.append(json.loads(decision_path.read_text(encoding="utf-8")))
            return 0

        with (
            patch("hyops.commands.rebuild.require_runtime_selection"),
            patch("hyops.commands.rebuild.resolve_runtime_paths", return_value=paths),
            patch("hyops.commands.rebuild.ensure_layout"),
            patch("hyops.commands.rebuild.new_run_id", return_value="rebuild-test"),
            patch("hyops.commands.rebuild.cmd_preflight.run", return_value=0),
            patch("hyops.commands.rebuild.cmd_apply.run", side_effect=run_phase),
        ):
            rc = run(
                _namespace(
                    root,
                    skip_preflight=skip_preflight,
                    reason=reason,
                )
            )

        summary_path = (
            root
            / "logs/rebuild/platform__test__module/rebuild-test"
            / "rebuild_summary.json"
        )
        summary = json.loads(summary_path.read_text(encoding="utf-8"))
        return rc, observed, summary

    def test_checked_rebuild_records_passed_preflight_before_destroy(self) -> None:
        rc, observed, summary = self._run(
            skip_preflight=False,
            reason=None,
        )

        self.assertEqual(rc, 0)
        self.assertEqual(len(observed), 2)
        self.assertEqual(observed[0]["status"], "passed")
        self.assertEqual(observed[0]["guarantee"], "established")
        self.assertEqual(summary["preflight"], observed[0])

    def test_bypassed_rebuild_records_reason_before_destroy(self) -> None:
        rc, observed, summary = self._run(
            skip_preflight=True,
            reason="controlled rebuild recovery",
        )

        self.assertEqual(rc, 0)
        self.assertEqual(len(observed), 2)
        self.assertEqual(observed[0]["status"], "bypassed")
        self.assertEqual(observed[0]["guarantee"], "not-established")
        self.assertEqual(observed[0]["reason"], "controlled rebuild recovery")
        self.assertEqual(summary["preflight"], observed[0])


if __name__ == "__main__":
    import unittest

    unittest.main()
