from __future__ import annotations

import hashlib
import os
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import patch

from hyops.runtime import proc
from hyops.blueprint.command import (
    _automatic_lab_restore_eligible,
    _configure_containerlab_restore,
    _lab_restore_phase,
    _run_lab_restore,
    _select_lab_restore_mode,
)


def _namespace(**overrides):
    values = {
        "restore_labs": False,
        "skip_lab_restore": False,
        "overwrite_labs": False,
        "overwrite_images": False,
        "yes": True,
        "json": False,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def _payload():
    return {
        "archive_before_destroy": {
            "module_ref": "platform/linux/eve-ng-lab-archive",
            "state_instance": "lab_archive",
            "inputs": {
                "inventory_state_ref": "platform/test/vm#lab_vm",
                "eveng_lab_archive_action": "export",
                "eveng_lab_archive_capture_device_configs": True,
                "eveng_lab_archive_include_node_state": True,
                "eveng_lab_archive_stop_running_nodes": False,
            },
        }
    }


def _containerlab_payload(source_dir: Path | None = None):
    inputs = {
        "containerlab_lab_restore_latest": True,
        "containerlab_lab_restore_require_source_match": True,
        "containerlab_lab_topology_relpath": "lab.clab.yml",
    }
    if source_dir is not None:
        inputs["containerlab_lab_source_dir"] = str(source_dir)
    return {
        "steps": [
            {
                "id": "containerlab_lab",
                "module_ref": "platform/linux/containerlab-lab",
                "state_instance": "containerlab_lab",
                "inputs": inputs,
            }
        ]
    }


def _containerlab_recovery_files(root: Path, topology: bytes = b"archived topology") -> None:
    recovery = root / "artifacts" / "containerlab" / "recovery"
    recovery.mkdir(parents=True)
    archive = recovery / "latest.tar.gz"
    archive.write_bytes(b"containerlab recovery")
    Path(f"{archive}.sha256").write_text("a" * 64 + "\n", encoding="utf-8")
    Path(f"{archive}.json").write_text(
        '{"topology_sha256":"'
        + hashlib.sha256(topology).hexdigest()
        + '"}\n',
        encoding="utf-8",
    )


class BlueprintLabRestoreTest(TestCase):
    def test_containerlab_restore_choice_is_explicit_after_destroy(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _containerlab_recovery_files(root)
            payload = _containerlab_payload()
            paths = SimpleNamespace(root=root, state_dir=root / "state")
            ns = _namespace(yes=False)
            with (
                patch(
                    "hyops.blueprint.command.module_state_status",
                    return_value="destroyed",
                ),
                patch("hyops.blueprint.command.sys.stdin.isatty", return_value=True),
                patch("hyops.blueprint.command.sys.stdout.isatty", return_value=True),
                patch("builtins.input", return_value="1"),
            ):
                handled, confirmed = _configure_containerlab_restore(
                    ns, payload, paths
                )

        self.assertTrue(handled)
        self.assertTrue(confirmed)
        self.assertTrue(
            payload["steps"][0]["inputs"]["containerlab_lab_restore_latest"]
        )
        self.assertTrue(ns._containerlab_restore_handled)

    def test_containerlab_clean_deploy_choice_disables_restore(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _containerlab_recovery_files(root)
            payload = _containerlab_payload()
            paths = SimpleNamespace(root=root, state_dir=root / "state")
            ns = _namespace(yes=False)
            with (
                patch(
                    "hyops.blueprint.command.module_state_status",
                    return_value="destroyed",
                ),
                patch("hyops.blueprint.command.sys.stdin.isatty", return_value=True),
                patch("hyops.blueprint.command.sys.stdout.isatty", return_value=True),
                patch("builtins.input", return_value="2"),
            ):
                handled, confirmed = _configure_containerlab_restore(
                    ns, payload, paths
                )

        self.assertTrue(handled)
        self.assertTrue(confirmed)
        self.assertFalse(
            payload["steps"][0]["inputs"]["containerlab_lab_restore_latest"]
        )

    def test_containerlab_topology_conflict_can_restore_archived_authority(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "source"
            source.mkdir()
            (source / "lab.clab.yml").write_bytes(b"controller topology")
            _containerlab_recovery_files(root)
            payload = _containerlab_payload(source)
            paths = SimpleNamespace(root=root, state_dir=root / "state")
            ns = _namespace(yes=False)
            with (
                patch(
                    "hyops.blueprint.command.module_state_status",
                    return_value="destroyed",
                ),
                patch("hyops.blueprint.command.sys.stdin.isatty", return_value=True),
                patch("hyops.blueprint.command.sys.stdout.isatty", return_value=True),
                patch("builtins.input", return_value="1"),
            ):
                handled, confirmed = _configure_containerlab_restore(
                    ns, payload, paths
                )

        inputs = payload["steps"][0]["inputs"]
        self.assertTrue(handled)
        self.assertTrue(confirmed)
        self.assertTrue(inputs["containerlab_lab_restore_latest"])
        self.assertFalse(inputs["containerlab_lab_restore_require_source_match"])

    def test_containerlab_topology_conflict_can_use_controller_authority(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "source"
            source.mkdir()
            (source / "lab.clab.yml").write_bytes(b"controller topology")
            _containerlab_recovery_files(root)
            payload = _containerlab_payload(source)
            paths = SimpleNamespace(root=root, state_dir=root / "state")
            ns = _namespace(yes=False)
            with (
                patch(
                    "hyops.blueprint.command.module_state_status",
                    return_value="destroyed",
                ),
                patch("hyops.blueprint.command.sys.stdin.isatty", return_value=True),
                patch("hyops.blueprint.command.sys.stdout.isatty", return_value=True),
                patch("builtins.input", return_value="2"),
            ):
                handled, confirmed = _configure_containerlab_restore(
                    ns, payload, paths
                )

        inputs = payload["steps"][0]["inputs"]
        self.assertTrue(handled)
        self.assertTrue(confirmed)
        self.assertFalse(inputs["containerlab_lab_restore_latest"])
        self.assertTrue(inputs["containerlab_lab_restore_require_source_match"])

    def test_containerlab_matching_topology_uses_standard_restore_choice(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "source"
            source.mkdir()
            topology = b"matching topology"
            (source / "lab.clab.yml").write_bytes(topology)
            _containerlab_recovery_files(root, topology)
            payload = _containerlab_payload(source)
            paths = SimpleNamespace(root=root, state_dir=root / "state")
            ns = _namespace(yes=False)
            with (
                patch(
                    "hyops.blueprint.command.module_state_status",
                    return_value="destroyed",
                ),
                patch("hyops.blueprint.command.sys.stdin.isatty", return_value=True),
                patch("hyops.blueprint.command.sys.stdout.isatty", return_value=True),
                patch("builtins.input", return_value="1"),
            ):
                handled, confirmed = _configure_containerlab_restore(
                    ns, payload, paths
                )

        inputs = payload["steps"][0]["inputs"]
        self.assertTrue(handled)
        self.assertTrue(confirmed)
        self.assertTrue(inputs["containerlab_lab_restore_latest"])
        self.assertTrue(inputs["containerlab_lab_restore_require_source_match"])

    def test_containerlab_explicit_restore_accepts_archived_topology(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "source"
            source.mkdir()
            (source / "lab.clab.yml").write_bytes(b"controller topology")
            _containerlab_recovery_files(root)
            payload = _containerlab_payload(source)
            paths = SimpleNamespace(root=root, state_dir=root / "state")
            with patch(
                "hyops.blueprint.command.module_state_status",
                return_value="destroyed",
            ):
                handled, confirmed = _configure_containerlab_restore(
                    _namespace(restore_labs=True), payload, paths
                )

        inputs = payload["steps"][0]["inputs"]
        self.assertTrue(handled)
        self.assertFalse(confirmed)
        self.assertTrue(inputs["containerlab_lab_restore_latest"])
        self.assertFalse(inputs["containerlab_lab_restore_require_source_match"])

    def test_containerlab_unattended_topology_conflict_fails_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "source"
            source.mkdir()
            (source / "lab.clab.yml").write_bytes(b"controller topology")
            _containerlab_recovery_files(root)
            paths = SimpleNamespace(root=root, state_dir=root / "state")
            with (
                patch(
                    "hyops.blueprint.command.module_state_status",
                    return_value="destroyed",
                ),
                self.assertRaisesRegex(ValueError, "--restore-labs"),
            ):
                _configure_containerlab_restore(
                    _namespace(yes=True), _containerlab_payload(source), paths
                )

    def test_containerlab_missing_controller_topology_can_restore_archive(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "missing-source"
            _containerlab_recovery_files(root)
            payload = _containerlab_payload(source)
            paths = SimpleNamespace(root=root, state_dir=root / "state")
            ns = _namespace(yes=False)
            with (
                patch(
                    "hyops.blueprint.command.module_state_status",
                    return_value="destroyed",
                ),
                patch("hyops.blueprint.command.sys.stdin.isatty", return_value=True),
                patch("hyops.blueprint.command.sys.stdout.isatty", return_value=True),
                patch("builtins.input", return_value="1"),
            ):
                handled, confirmed = _configure_containerlab_restore(
                    ns, payload, paths
                )

        inputs = payload["steps"][0]["inputs"]
        self.assertTrue(handled)
        self.assertTrue(confirmed)
        self.assertTrue(inputs["containerlab_lab_restore_latest"])
        self.assertFalse(inputs["containerlab_lab_restore_require_source_match"])

    def test_containerlab_skip_rejects_missing_controller_topology(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "missing-source"
            _containerlab_recovery_files(root)
            paths = SimpleNamespace(root=root, state_dir=root / "state")
            with (
                patch(
                    "hyops.blueprint.command.module_state_status",
                    return_value="destroyed",
                ),
                self.assertRaisesRegex(ValueError, "controller topology is unavailable"),
            ):
                _configure_containerlab_restore(
                    _namespace(skip_lab_restore=True),
                    _containerlab_payload(source),
                    paths,
                )

    def test_containerlab_invalid_topology_metadata_fails_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "source"
            source.mkdir()
            (source / "lab.clab.yml").write_bytes(b"controller topology")
            _containerlab_recovery_files(root)
            metadata = (
                root
                / "artifacts"
                / "containerlab"
                / "recovery"
                / "latest.tar.gz.json"
            )
            metadata.write_text("{}\n", encoding="utf-8")
            paths = SimpleNamespace(root=root, state_dir=root / "state")
            with (
                patch(
                    "hyops.blueprint.command.module_state_status",
                    return_value="destroyed",
                ),
                self.assertRaisesRegex(ValueError, "no valid topology identity"),
            ):
                _configure_containerlab_restore(
                    _namespace(), _containerlab_payload(source), paths
                )

    def test_containerlab_cancel_choice_stops_deploy(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _containerlab_recovery_files(root)
            paths = SimpleNamespace(root=root, state_dir=root / "state")
            ns = _namespace(yes=False)
            with (
                patch(
                    "hyops.blueprint.command.module_state_status",
                    return_value="destroyed",
                ),
                patch("hyops.blueprint.command.sys.stdin.isatty", return_value=True),
                patch("hyops.blueprint.command.sys.stdout.isatty", return_value=True),
                patch("builtins.input", return_value="3"),
            ):
                handled, confirmed = _configure_containerlab_restore(
                    ns, _containerlab_payload(), paths
                )

        self.assertTrue(handled)
        self.assertTrue(confirmed)
        self.assertTrue(ns._containerlab_restore_cancelled)

    def test_containerlab_restore_flags_do_not_enter_generic_archive_flow(self):
        ns = _namespace(restore_labs=True)
        ns._containerlab_restore_handled = True

        mode, archive = _select_lab_restore_mode(
            ns,
            _containerlab_payload(),
            SimpleNamespace(),
        )

        self.assertEqual(mode, "none")
        self.assertIsNone(archive)

    def test_containerlab_active_converge_does_not_replay_old_recovery(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _containerlab_recovery_files(root)
            payload = _containerlab_payload()
            paths = SimpleNamespace(root=root, state_dir=root / "state")
            with (
                patch(
                    "hyops.blueprint.command.module_state_status",
                    return_value="ok",
                ),
                patch("builtins.input") as prompt,
            ):
                handled, confirmed = _configure_containerlab_restore(
                    _namespace(yes=False), payload, paths
                )

        self.assertTrue(handled)
        self.assertFalse(confirmed)
        self.assertFalse(
            payload["steps"][0]["inputs"]["containerlab_lab_restore_latest"]
        )
        prompt.assert_not_called()

    def test_containerlab_active_restore_requires_overwrite(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _containerlab_recovery_files(root)
            paths = SimpleNamespace(root=root, state_dir=root / "state")
            with (
                patch(
                    "hyops.blueprint.command.module_state_status",
                    return_value="ok",
                ),
                self.assertRaisesRegex(ValueError, "requires --overwrite-labs"),
            ):
                _configure_containerlab_restore(
                    _namespace(restore_labs=True),
                    _containerlab_payload(),
                    paths,
                )

    def test_containerlab_active_overwrite_can_use_archived_topology(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "source"
            source.mkdir()
            (source / "lab.clab.yml").write_bytes(b"controller topology")
            _containerlab_recovery_files(root)
            payload = _containerlab_payload(source)
            paths = SimpleNamespace(root=root, state_dir=root / "state")
            with patch(
                "hyops.blueprint.command.module_state_status",
                return_value="ok",
            ):
                handled, confirmed = _configure_containerlab_restore(
                    _namespace(restore_labs=True, overwrite_labs=True),
                    payload,
                    paths,
                )

        inputs = payload["steps"][0]["inputs"]
        self.assertTrue(handled)
        self.assertFalse(confirmed)
        self.assertTrue(inputs["containerlab_lab_restore_latest"])
        self.assertFalse(inputs["containerlab_lab_restore_require_source_match"])

    def test_containerlab_incomplete_recovery_markers_fail_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            archive = root / "artifacts" / "containerlab" / "recovery" / "latest.tar.gz"
            archive.parent.mkdir(parents=True)
            archive.write_bytes(b"incomplete")
            paths = SimpleNamespace(root=root, state_dir=root / "state")
            with self.assertRaisesRegex(ValueError, "markers are incomplete"):
                _configure_containerlab_restore(
                    _namespace(), _containerlab_payload(), paths
                )

    def test_restore_phase_maps_long_running_tasks(self):
        self.assertEqual(
            _lab_restore_phase(
                "TASK [hybridops.helper.eveng_lab_archive : "
                "Stage referenced EVE-NG images] *****"
            ),
            "staging images",
        )
        self.assertEqual(
            _lab_restore_phase(
                "TASK [hybridops.helper.eveng_lab_archive : "
                "Inspect restored EVE-NG QEMU overlays] ***"
            ),
            "verifying node state",
        )
        self.assertEqual(
            _lab_restore_phase(
                "TASK [hybridops.app.gns3_lab_archive : Restore GNS3 lab state] ***"
            ),
            "restoring lab definitions",
        )
        self.assertEqual(
            _lab_restore_phase(
                "TASK [hybridops.app.containerlab_recovery : "
                "Extract recovery archive] ***"
            ),
            "restoring lab data",
        )
        self.assertEqual(_lab_restore_phase("ok: [eve-ng-01]"), "")

    def test_existing_target_does_not_require_automatic_restore(self):
        paths = SimpleNamespace(state_dir=Path("/tmp/state"))

        with patch(
            "hyops.blueprint.command.module_state_status",
            return_value="ok",
        ):
            eligible = _automatic_lab_restore_eligible(_payload(), paths)

        self.assertFalse(eligible)

    def test_destroyed_target_allows_automatic_restore(self):
        paths = SimpleNamespace(state_dir=Path("/tmp/state"))

        with patch(
            "hyops.blueprint.command.module_state_status",
            return_value="destroyed",
        ):
            eligible = _automatic_lab_restore_eligible(_payload(), paths)

        self.assertTrue(eligible)

    def test_existing_target_does_not_offer_available_archive(self):
        with tempfile.TemporaryDirectory() as tmp:
            archive = Path(tmp) / "labs.tar.gz"
            archive.write_bytes(b"portable labs")
            checksum = hashlib.sha256(archive.read_bytes()).hexdigest()
            paths = SimpleNamespace(state_dir=Path(tmp) / "state")
            state = {
                "outputs": {
                    "eveng_lab_archive_path": str(archive),
                    "eveng_lab_archive_sha256": checksum,
                }
            }
            with (
                patch(
                    "hyops.blueprint.command.read_module_state",
                    return_value=state,
                ),
                patch("builtins.input") as prompt,
            ):
                mode, selected = _select_lab_restore_mode(
                    _namespace(yes=False),
                    _payload(),
                    paths,
                    automatic_restore_eligible=False,
                )

        self.assertEqual(mode, "none")
        self.assertIsNotNone(selected)
        prompt.assert_not_called()

    def test_explicit_restore_uses_verified_archive(self):
        with tempfile.TemporaryDirectory() as tmp:
            archive = Path(tmp) / "labs.tar.gz"
            archive.write_bytes(b"portable labs")
            checksum = hashlib.sha256(archive.read_bytes()).hexdigest()
            paths = SimpleNamespace(state_dir=Path(tmp) / "state")
            state = {
                "outputs": {
                    "eveng_lab_archive_path": str(archive),
                    "eveng_lab_archive_sha256": checksum,
                }
            }
            with patch(
                "hyops.blueprint.command.read_module_state",
                return_value=state,
            ):
                mode, selected = _select_lab_restore_mode(
                    _namespace(restore_labs=True),
                    _payload(),
                    paths,
                )

        self.assertEqual(mode, "restore")
        self.assertEqual(
            selected,
            (archive.resolve(), checksum, None, "", None, ""),
        )

    def test_explicit_restore_requires_an_archive(self):
        paths = SimpleNamespace(state_dir=Path("/tmp/state"))
        with (
            patch(
                "hyops.blueprint.command.read_module_state",
                side_effect=FileNotFoundError,
            ),
            patch(
                "hyops.lab.migration.load_migration_archive",
                return_value=None,
            ),
            self.assertRaisesRegex(ValueError, "no verified lab archive"),
        ):
            _select_lab_restore_mode(
                _namespace(restore_labs=True),
                _payload(),
                paths,
            )

    def test_explicit_restore_accepts_staged_migration_archive(self):
        imported = (
            Path("/tmp/imported.tar.gz"),
            "d" * 64,
            None,
            "",
            None,
            "",
        )
        paths = SimpleNamespace(state_dir=Path("/tmp/state"))
        with (
            patch(
                "hyops.blueprint.command.read_module_state",
                side_effect=FileNotFoundError,
            ),
            patch(
                "hyops.lab.migration.load_migration_archive",
                return_value=imported,
            ),
        ):
            mode, selected = _select_lab_restore_mode(
                _namespace(restore_labs=True),
                _payload(),
                paths,
            )

        self.assertEqual(mode, "restore")
        self.assertEqual(selected, imported)

    def test_checksum_mismatch_stops_restore(self):
        with tempfile.TemporaryDirectory() as tmp:
            archive = Path(tmp) / "labs.tar.gz"
            archive.write_bytes(b"changed")
            paths = SimpleNamespace(state_dir=Path(tmp) / "state")
            state = {
                "outputs": {
                    "eveng_lab_archive_path": str(archive),
                    "eveng_lab_archive_sha256": "a" * 64,
                }
            }
            with (
                patch(
                    "hyops.blueprint.command.read_module_state",
                    return_value=state,
                ),
                self.assertRaisesRegex(ValueError, "checksum verification failed"),
            ):
                _select_lab_restore_mode(
                    _namespace(restore_labs=True),
                    _payload(),
                    paths,
                )

    def test_restore_reuses_target_contract_and_protects_existing_labs(self):
        archive = (
            Path("/tmp/labs.tar.gz"),
            "b" * 64,
            None,
            "",
            None,
            "",
        )
        with patch(
            "hyops.blueprint.command.run_step_module_command",
            return_value=0,
        ) as command:
            rc = _run_lab_restore(
                _namespace(restore_labs=True),
                _payload(),
                SimpleNamespace(),
                archive,
            )

        self.assertEqual(rc, 0)
        step = command.call_args.args[0]
        self.assertEqual(step["id"], "restore_archived_labs")
        self.assertEqual(
            step["inputs"]["inventory_state_ref"],
            "platform/test/vm#lab_vm",
        )
        self.assertEqual(step["inputs"]["eveng_lab_archive_action"], "restore")
        self.assertEqual(
            step["inputs"]["eveng_lab_archive_expected_sha256"],
            "b" * 64,
        )
        self.assertFalse(step["inputs"]["eveng_lab_archive_overwrite"])
        self.assertFalse(step["inputs"]["eveng_lab_archive_capture_device_configs"])
        self.assertFalse(step["inputs"]["eveng_lab_archive_include_node_state"])
        self.assertFalse(step["inputs"]["eveng_lab_archive_stop_running_nodes"])

    def test_restore_hides_nested_progress_and_elapsed_time(self):
        archive = (
            Path("/tmp/labs.tar.gz"),
            "b" * 64,
            None,
            "",
            None,
            "",
        )

        def run_restore(*_args):
            self.assertEqual(os.environ.get("HYOPS_PROGRESS_CHILD"), "1")
            return 0

        with (
            patch(
                "hyops.blueprint.command.run_step_module_command",
                side_effect=run_restore,
            ),
            patch("hyops.blueprint.command.ProgressDisplay") as progress_class,
        ):
            os.environ.pop("HYOPS_PROGRESS_CHILD", None)
            try:
                rc = _run_lab_restore(
                    _namespace(restore_labs=True),
                    _payload(),
                    SimpleNamespace(),
                    archive,
                )
            finally:
                self.assertNotIn("HYOPS_PROGRESS_CHILD", os.environ)

        self.assertEqual(rc, 0)
        self.assertFalse(progress_class.call_args.kwargs["show_elapsed"])

    def test_restore_reports_the_current_ansible_phase(self):
        archive = (
            Path("/tmp/labs.tar.gz"),
            "b" * 64,
            None,
            "",
            None,
            "",
        )

        def run_restore(*_args):
            proc._notify_stream_observers(
                "stdout",
                "TASK [hybridops.helper.eveng_lab_archive : "
                "Stage referenced EVE-NG images] *****\n",
            )
            return 0

        with (
            patch(
                "hyops.blueprint.command.run_step_module_command",
                side_effect=run_restore,
            ),
            patch("hyops.blueprint.command.ProgressDisplay") as progress_class,
        ):
            rc = _run_lab_restore(
                _namespace(restore_labs=True),
                _payload(),
                SimpleNamespace(),
                archive,
            )

        self.assertEqual(rc, 0)
        progress_class.return_value.update.assert_called_with(
            "restore_archived_labs",
            "Lab restore: staging images",
        )

    def test_restore_includes_verified_node_state(self):
        archive = (
            Path("/tmp/labs.tar.gz"),
            "b" * 64,
            Path("/tmp/labs.tar.gz.node-state.tar.gz"),
            "c" * 64,
            None,
            "",
        )
        with patch(
            "hyops.blueprint.command.run_step_module_command",
            return_value=0,
        ) as command:
            rc = _run_lab_restore(
                _namespace(restore_labs=True),
                _payload(),
                SimpleNamespace(),
                archive,
            )

        self.assertEqual(rc, 0)
        inputs = command.call_args.args[0]["inputs"]
        self.assertTrue(inputs["eveng_lab_archive_restore_node_state"])
        self.assertEqual(
            inputs["eveng_lab_archive_node_state_path"],
            "/tmp/labs.tar.gz.node-state.tar.gz",
        )
        self.assertEqual(
            inputs["eveng_lab_archive_node_state_expected_sha256"],
            "c" * 64,
        )

    def test_restore_retains_verified_node_state_after_prior_restore(self):
        with tempfile.TemporaryDirectory() as tmp:
            archive = Path(tmp) / "labs.tar.gz"
            archive.write_bytes(b"portable labs")
            checksum = hashlib.sha256(archive.read_bytes()).hexdigest()
            node_archive = Path(tmp) / "labs.tar.gz.node-state.tar.gz"
            node_archive.write_bytes(b"qemu overlays")
            node_checksum = hashlib.sha256(node_archive.read_bytes()).hexdigest()
            paths = SimpleNamespace(state_dir=Path(tmp) / "state")
            state = {
                "outputs": {
                    "eveng_lab_archive_path": str(archive),
                    "eveng_lab_archive_sha256": checksum,
                    "eveng_lab_archive_node_state_included": False,
                    "eveng_lab_archive_node_state_archive_path": str(node_archive),
                    "eveng_lab_archive_node_state_sha256": node_checksum,
                }
            }
            with patch(
                "hyops.blueprint.command.read_module_state",
                return_value=state,
            ):
                mode, selected = _select_lab_restore_mode(
                    _namespace(restore_labs=True),
                    _payload(),
                    paths,
                )

        self.assertEqual(mode, "restore")
        self.assertEqual(
            selected,
            (
                archive.resolve(),
                checksum,
                node_archive.resolve(),
                node_checksum,
                None,
                "",
            ),
        )

    def test_restore_retains_migrated_images_after_a_later_lab_export(self):
        with tempfile.TemporaryDirectory() as tmp:
            archive = Path(tmp) / "latest-labs.tar.gz"
            archive.write_bytes(b"latest portable labs")
            checksum = hashlib.sha256(archive.read_bytes()).hexdigest()
            image_archive = Path(tmp) / "imported-images.tar.gz"
            image_archive.write_bytes(b"referenced bases")
            image_checksum = hashlib.sha256(image_archive.read_bytes()).hexdigest()
            paths = SimpleNamespace(state_dir=Path(tmp) / "state")
            payload = _payload() | {"blueprint_ref": "gcp/eve-ng@v1"}
            state = {
                "outputs": {
                    "eveng_lab_archive_path": str(archive),
                    "eveng_lab_archive_sha256": checksum,
                }
            }
            with (
                patch(
                    "hyops.blueprint.command.read_module_state",
                    return_value=state,
                ),
                patch(
                    "hyops.lab.migration.load_migration_images",
                    return_value=(image_archive.resolve(), image_checksum),
                ) as migrated_images,
            ):
                mode, selected = _select_lab_restore_mode(
                    _namespace(restore_labs=True),
                    payload,
                    paths,
                )

        self.assertEqual(mode, "restore")
        self.assertEqual(selected[0], archive.resolve())
        self.assertEqual(selected[4:], (image_archive.resolve(), image_checksum))
        migrated_images.assert_called_once()

    def test_restore_uses_image_metadata_published_by_prior_restore(self):
        with tempfile.TemporaryDirectory() as tmp:
            archive = Path(tmp) / "labs.tar.gz"
            archive.write_bytes(b"portable labs")
            checksum = hashlib.sha256(archive.read_bytes()).hexdigest()
            image_archive = Path(tmp) / "images.tar.gz"
            image_archive.write_bytes(b"referenced bases")
            image_checksum = hashlib.sha256(image_archive.read_bytes()).hexdigest()
            paths = SimpleNamespace(state_dir=Path(tmp) / "state")
            state = {
                "outputs": {
                    "eveng_lab_archive_path": str(archive),
                    "eveng_lab_archive_sha256": checksum,
                    "eveng_lab_archive_images_included": True,
                    "eveng_lab_archive_images_archive_path": str(image_archive),
                    "eveng_lab_archive_images_sha256": image_checksum,
                }
            }
            with patch(
                "hyops.blueprint.command.read_module_state",
                return_value=state,
            ):
                mode, selected = _select_lab_restore_mode(
                    _namespace(restore_labs=True),
                    _payload(),
                    paths,
                )

        self.assertEqual(mode, "restore")
        self.assertEqual(selected[4:], (image_archive.resolve(), image_checksum))

    def test_restore_includes_verified_referenced_images(self):
        archive = (
            Path("/tmp/labs.tar.gz"),
            "b" * 64,
            None,
            "",
            Path("/tmp/labs.images.tar.gz"),
            "e" * 64,
        )
        with patch(
            "hyops.blueprint.command.run_step_module_command",
            return_value=0,
        ) as command:
            rc = _run_lab_restore(
                _namespace(restore_labs=True),
                _payload(),
                SimpleNamespace(),
                archive,
            )

        self.assertEqual(rc, 0)
        inputs = command.call_args.args[0]["inputs"]
        self.assertTrue(inputs["eveng_lab_archive_restore_images"])
        self.assertEqual(
            inputs["eveng_lab_archive_images_path"],
            "/tmp/labs.images.tar.gz",
        )
        self.assertEqual(
            inputs["eveng_lab_archive_images_expected_sha256"],
            "e" * 64,
        )
        self.assertFalse(inputs["eveng_lab_archive_overwrite_images"])

    def test_image_overwrite_is_separate_from_lab_overwrite(self):
        archive = (
            Path("/tmp/labs.tar.gz"),
            "b" * 64,
            None,
            "",
            Path("/tmp/labs.images.tar.gz"),
            "e" * 64,
        )
        with patch(
            "hyops.blueprint.command.run_step_module_command",
            return_value=0,
        ) as command:
            rc = _run_lab_restore(
                _namespace(
                    restore_labs=True,
                    overwrite_labs=False,
                    overwrite_images=True,
                ),
                _payload(),
                SimpleNamespace(),
                archive,
            )

        self.assertEqual(rc, 0)
        inputs = command.call_args.args[0]["inputs"]
        self.assertFalse(inputs["eveng_lab_archive_overwrite"])
        self.assertTrue(inputs["eveng_lab_archive_overwrite_images"])

    def test_gns3_restore_uses_declared_archive_contract(self):
        payload = {
            "archive_before_destroy": {
                "module_ref": "platform/linux/gns3-lab-archive",
                "state_instance": "gns3_archive",
                "contract_prefix": "gns3_lab_archive",
                "node_state": False,
                "restore_overwrite_default": True,
                "inputs": {
                    "inventory_state_ref": "platform/test/vm#gns3_vm",
                    "gns3_lab_archive_action": "export",
                },
            }
        }
        archive = (
            Path("/tmp/gns3-labs.tar.gz"),
            "d" * 64,
            None,
            "",
            None,
            "",
        )
        with patch(
            "hyops.blueprint.command.run_step_module_command",
            return_value=0,
        ) as command:
            rc = _run_lab_restore(
                _namespace(restore_labs=True),
                payload,
                SimpleNamespace(),
                archive,
            )

        self.assertEqual(rc, 0)
        inputs = command.call_args.args[0]["inputs"]
        self.assertEqual(inputs["gns3_lab_archive_action"], "restore")
        self.assertEqual(
            inputs["gns3_lab_archive_path"],
            "/tmp/gns3-labs.tar.gz",
        )
        self.assertEqual(
            inputs["gns3_lab_archive_expected_sha256"],
            "d" * 64,
        )
        self.assertTrue(inputs["gns3_lab_archive_overwrite"])
        self.assertNotIn("gns3_lab_archive_include_node_state", inputs)
