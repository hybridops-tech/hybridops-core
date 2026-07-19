from __future__ import annotations

import hashlib
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import patch

from hyops.blueprint.command import (
    _run_lab_restore,
    _select_lab_restore_mode,
)


def _namespace(**overrides):
    values = {
        "restore_labs": False,
        "skip_lab_restore": False,
        "overwrite_labs": False,
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
                "eveng_lab_archive_include_node_state": True,
                "eveng_lab_archive_stop_running_nodes": True,
            },
        }
    }


class BlueprintLabRestoreTest(TestCase):
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
        self.assertEqual(selected, (archive.resolve(), checksum, None, ""))

    def test_explicit_restore_requires_an_archive(self):
        paths = SimpleNamespace(state_dir=Path("/tmp/state"))
        with patch(
            "hyops.blueprint.command.read_module_state",
            side_effect=FileNotFoundError,
        ), self.assertRaisesRegex(ValueError, "no verified lab archive"):
            _select_lab_restore_mode(
                _namespace(restore_labs=True),
                _payload(),
                paths,
            )

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
            with patch(
                "hyops.blueprint.command.read_module_state",
                return_value=state,
            ), self.assertRaisesRegex(ValueError, "checksum verification failed"):
                _select_lab_restore_mode(
                    _namespace(restore_labs=True),
                    _payload(),
                    paths,
                )

    def test_restore_reuses_target_contract_and_protects_existing_labs(self):
        archive = (Path("/tmp/labs.tar.gz"), "b" * 64, None, "")
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
        self.assertFalse(step["inputs"]["eveng_lab_archive_include_node_state"])
        self.assertFalse(step["inputs"]["eveng_lab_archive_stop_running_nodes"])

    def test_restore_includes_verified_node_state(self):
        archive = (
            Path("/tmp/labs.tar.gz"),
            "b" * 64,
            Path("/tmp/labs.tar.gz.node-state.tar.gz"),
            "c" * 64,
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
        archive = (Path("/tmp/gns3-labs.tar.gz"), "d" * 64, None, "")
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
