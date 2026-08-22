"""Tests for module state while provider mutations are in progress."""

from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import patch

from hyops.commands._apply_execute import run_single
from hyops.runtime.module_state import read_module_state, write_module_state
from hyops.runtime.paths import RuntimePaths


class MutationStateContractTest(TestCase):
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
            inputs={"resource_name": "partial-resource"},
            required_credentials=[],
            dependencies=[],
            dependency_warnings=[],
            outputs_publish=[],
        )

    def _run_apply(self, root: Path, driver) -> int:
        paths = RuntimePaths.from_root(root)
        with (
            patch(
                "hyops.commands._apply_execute.resolve_module",
                return_value=self._resolved(root),
            ),
            patch("hyops.commands._apply_execute.REGISTRY.validate_execution"),
            patch(
                "hyops.commands._apply_execute.REGISTRY.resolve",
                return_value=driver,
            ),
            patch(
                "hyops.commands._apply_execute.new_run_id",
                return_value="apply-mutation-state-test",
            ),
            patch("hyops.commands._apply_execute.stamp_runtime"),
        ):
            return run_single(
                paths=paths,
                env_name="test",
                command_name="apply",
                module_ref_raw="platform/test/module",
                module_root=root / "modules",
                inputs_file=None,
                out_dir=None,
                skip_preflight=False,
                state_instance="slot",
            )

    def test_apply_invalidates_destroyed_state_before_provider_mutation(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            paths = RuntimePaths.from_root(root)
            write_module_state(
                paths.state_dir,
                "platform/test/module",
                {
                    "status": "destroyed",
                    "outputs": {"resource_id": "previous-resource"},
                },
                state_instance="slot",
            )
            state_seen_by_apply = {}

            def driver(request):
                if request["command"] == "preflight":
                    return {"status": "ok"}
                state_seen_by_apply.update(
                    read_module_state(
                        paths.state_dir,
                        "platform/test/module",
                        state_instance="slot",
                    )
                )
                return {"status": "error", "error": "partial infrastructure apply"}

            rc = self._run_apply(root, driver)
            final_state = read_module_state(
                paths.state_dir,
                "platform/test/module",
                state_instance="slot",
            )

        self.assertEqual(rc, 1)
        self.assertEqual(state_seen_by_apply["status"], "running")
        self.assertEqual(state_seen_by_apply["active_command"], "apply")
        self.assertEqual(final_state["status"], "error")
        self.assertEqual(final_state["last_error"], "partial infrastructure apply")
        self.assertEqual(
            final_state["outputs"], {"resource_id": "previous-resource"}
        )

    def test_failed_initial_apply_creates_nonterminal_state(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            paths = RuntimePaths.from_root(root)

            def driver(request):
                if request["command"] == "preflight":
                    return {"status": "ok"}
                return {"status": "error", "error": "provider failed after create"}

            rc = self._run_apply(root, driver)
            final_state = read_module_state(
                paths.state_dir,
                "platform/test/module",
                state_instance="slot",
            )

        self.assertEqual(rc, 1)
        self.assertEqual(final_state["status"], "error")
        self.assertEqual(final_state["failed_command"], "apply")

    def test_successful_apply_replaces_running_marker_with_ok_state(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            paths = RuntimePaths.from_root(root)
            state_seen_by_apply = {}

            def driver(request):
                if request["command"] == "preflight":
                    return {"status": "ok"}
                state_seen_by_apply.update(
                    read_module_state(
                        paths.state_dir,
                        "platform/test/module",
                        state_instance="slot",
                    )
                )
                return {"status": "ok", "normalized_outputs": {}}

            rc = self._run_apply(root, driver)
            final_state = read_module_state(
                paths.state_dir,
                "platform/test/module",
                state_instance="slot",
            )

        self.assertEqual(rc, 0)
        self.assertEqual(state_seen_by_apply["status"], "running")
        self.assertEqual(final_state["status"], "ok")
        self.assertNotIn("active_command", final_state)

    def test_preflight_failure_does_not_invalidate_destroyed_state(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            paths = RuntimePaths.from_root(root)
            write_module_state(
                paths.state_dir,
                "platform/test/module",
                {"status": "destroyed", "outputs": {}},
                state_instance="slot",
            )

            def driver(request):
                self.assertEqual(request["command"], "preflight")
                return {"status": "error", "error": "credentials unavailable"}

            rc = self._run_apply(root, driver)
            final_state = read_module_state(
                paths.state_dir,
                "platform/test/module",
                state_instance="slot",
            )

        self.assertEqual(rc, 1)
        self.assertEqual(final_state["status"], "destroyed")

    def test_provider_is_not_started_when_mutation_state_cannot_be_persisted(
        self,
    ) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            calls = []

            def driver(request):
                calls.append(request["command"])
                return {"status": "ok"}

            with patch(
                "hyops.commands._apply_execute.write_module_state",
                side_effect=OSError("state disk is full"),
            ):
                rc = self._run_apply(root, driver)

        self.assertEqual(rc, 1)
        self.assertEqual(calls, ["preflight"])
