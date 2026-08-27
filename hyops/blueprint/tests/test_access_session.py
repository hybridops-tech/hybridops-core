from __future__ import annotations

from datetime import datetime, timedelta, timezone
import io
import json
from pathlib import Path
from types import SimpleNamespace
import tempfile
from unittest import TestCase
from unittest.mock import patch

from hyops.blueprint.access_session import (
    LifecycleBusy,
    LifecycleLock,
    effective_status,
    extend_session,
    load_session,
    session_state_path,
    start_session,
)
from hyops.blueprint.command import run_destroy, run_rebuild, run_session
from hyops.runtime.exitcodes import OPERATOR_ERROR


def _paths(root: Path) -> SimpleNamespace:
    return SimpleNamespace(
        root=root,
        meta_dir=root / "meta",
        logs_dir=root / "logs",
    )


class AccessSessionStateTests(TestCase):
    def test_start_persists_authority_and_run_record(self) -> None:
        now = datetime(2026, 8, 26, 12, 0, tzinfo=timezone.utc)
        with tempfile.TemporaryDirectory() as tmp:
            paths = _paths(Path(tmp))
            record = start_session(
                paths,
                env_name="demo-lab",
                blueprint_ref="gcp/eve-ng@v1",
                state_ref="platform/gcp/platform-vm#gcp_eve_ng_vm",
                resource_generation="generation-one",
                duration_seconds=3600,
                expiry_action="protected-release",
                now=now,
                pid=1234,
            )

            stored = load_session(paths, "gcp/eve-ng@v1")
            self.assertEqual(stored, record)
            self.assertEqual(record["status"], "active")
            self.assertEqual(record["deadline_at"], "2026-08-26T13:00:00Z")
            self.assertEqual(record["resource_generation"], "generation-one")
            self.assertTrue(Path(record["run_record"]).is_file())
            self.assertNotIn("credential", json.dumps(record).lower())

    def test_effective_status_reports_lost_supervision(self) -> None:
        record = {
            "status": "active",
            "deadline_at": "2026-08-26T13:00:00Z",
        }
        before = datetime(2026, 8, 26, 12, 30, tzinfo=timezone.utc)
        after = datetime(2026, 8, 26, 13, 1, tzinfo=timezone.utc)
        self.assertEqual(
            effective_status(record, now=before, supervisor_is_running=False),
            "unsupervised",
        )
        self.assertEqual(
            effective_status(record, now=after, supervisor_is_running=False),
            "overdue-unsupervised",
        )

    def test_extend_adds_to_the_existing_deadline(self) -> None:
        now = datetime(2026, 8, 26, 12, 0, tzinfo=timezone.utc)
        with tempfile.TemporaryDirectory() as tmp:
            paths = _paths(Path(tmp))
            record = start_session(
                paths,
                env_name="demo-lab",
                blueprint_ref="gcp/gns3@v1",
                state_ref="platform/gcp/platform-vm#gcp_gns3_vm",
                resource_generation="generation-one",
                duration_seconds=3600,
                expiry_action="protected-release",
                now=now,
            )
            extend_session(
                paths,
                record,
                seconds=1800,
                now=now + timedelta(minutes=10),
            )

            self.assertEqual(record["deadline_at"], "2026-08-26T13:30:00Z")
            self.assertEqual(record["extension_count"], 1)

    def test_lifecycle_lock_rejects_a_second_owner(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            paths = _paths(Path(tmp))
            with LifecycleLock(paths, "first operation"):
                with self.assertRaisesRegex(LifecycleBusy, "first operation"):
                    with LifecycleLock(paths, "second operation"):
                        pass
            self.assertFalse((paths.meta_dir / "blueprint_lifecycle.lock").exists())

    def test_session_file_is_scoped_by_blueprint(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = session_state_path(_paths(Path(tmp)), "gcp/containerlab@v1")
            self.assertEqual(path.name, "gcp_containerlab_v1.json")

    def test_lifecycle_lock_blocks_destroy_and_rebuild(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            paths = _paths(Path(tmp))
            cases = (
                (run_destroy, "_run_destroy_unlocked"),
                (run_rebuild, "_run_rebuild_unlocked"),
            )
            for command, implementation in cases:
                ns = SimpleNamespace(root=tmp, env=None, execute=True)
                with (
                    self.subTest(command=command.__name__),
                    LifecycleLock(paths, "active session mutation"),
                    patch("hyops.blueprint.command.require_runtime_selection"),
                    patch(
                        "hyops.blueprint.command.resolve_runtime_paths",
                        return_value=paths,
                    ),
                    patch("hyops.blueprint.command.ensure_layout"),
                    patch(
                        f"hyops.blueprint.command.{implementation}"
                    ) as mutation,
                    patch("sys.stdout", io.StringIO()),
                ):
                    self.assertEqual(command(ns), OPERATOR_ERROR)
                mutation.assert_not_called()

    def test_cancel_records_a_final_outcome(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            paths = _paths(Path(tmp))
            start_session(
                paths,
                env_name="demo-lab",
                blueprint_ref="gcp/eve-ng@v1",
                state_ref="platform/gcp/platform-vm#gcp_eve_ng_vm",
                resource_generation="generation-one",
                duration_seconds=3600,
                expiry_action="protected-release",
            )
            ns = SimpleNamespace(
                root=None,
                env="demo-lab",
                session_cmd="cancel",
                json=False,
            )
            with (
                patch(
                    "hyops.blueprint.command._resolve_and_validate",
                    return_value={"blueprint_ref": "gcp/eve-ng@v1"},
                ),
                patch("hyops.blueprint.command.require_runtime_selection"),
                patch(
                    "hyops.blueprint.command.resolve_runtime_paths",
                    return_value=paths,
                ),
                patch("sys.stdout", io.StringIO()),
            ):
                self.assertEqual(run_session(ns), 0)

            record = load_session(paths, "gcp/eve-ng@v1")
            self.assertEqual(record["status"], "cancelled")
            self.assertEqual(
                record["outcome"]["reason"],
                "expiry cancelled by operator",
            )
            run_record = json.loads(
                Path(record["run_record"]).read_text(encoding="utf-8")
            )
            self.assertEqual(run_record["deadline_at"], record["deadline_at"])
            self.assertEqual(run_record["expiry_action"], "protected-release")
            self.assertEqual(run_record["status"], "cancelled")

    def test_extend_rejects_a_changed_resource_generation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            paths = _paths(Path(tmp))
            start_session(
                paths,
                env_name="demo-lab",
                blueprint_ref="gcp/gns3@v1",
                state_ref="platform/gcp/platform-vm#gcp_gns3_vm",
                resource_generation="generation-one",
                duration_seconds=3600,
                expiry_action="protected-release",
            )
            ns = SimpleNamespace(
                root=None,
                env="demo-lab",
                session_cmd="extend",
                minutes=30,
                json=False,
            )
            with (
                patch(
                    "hyops.blueprint.command._resolve_and_validate",
                    return_value={"blueprint_ref": "gcp/gns3@v1"},
                ),
                patch("hyops.blueprint.command.require_runtime_selection"),
                patch(
                    "hyops.blueprint.command.resolve_runtime_paths",
                    return_value=paths,
                ),
                patch(
                    "hyops.blueprint.command._current_access_generation",
                    return_value="generation-two",
                ),
                patch("sys.stdout", io.StringIO()),
            ):
                self.assertEqual(run_session(ns), OPERATOR_ERROR)

            record = load_session(paths, "gcp/gns3@v1")
            self.assertEqual(record["status"], "stale-generation")
