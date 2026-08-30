from __future__ import annotations

import hashlib
import io
import json
import subprocess
import tarfile
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import patch

from hyops.lab.migration import (
    _capture_stream,
    capture_existing_lab,
    inspect_migration_archive,
    load_migration_archive,
    migration_record_path,
    stage_migration_archive,
)
from hyops.runtime.layout import ensure_layout
from hyops.runtime.paths import RuntimePaths


def _write_tar(path: Path, files: dict[str, bytes]) -> None:
    with tarfile.open(path, mode="w:gz") as handle:
        for name, payload in files.items():
            member = tarfile.TarInfo(name=name)
            member.size = len(payload)
            handle.addfile(member, io.BytesIO(payload))


def _tar_bytes(files: dict[str, bytes]) -> bytes:
    output = io.BytesIO()
    with tarfile.open(fileobj=output, mode="w:gz") as handle:
        for name, payload in files.items():
            member = tarfile.TarInfo(name=name)
            member.size = len(payload)
            handle.addfile(member, io.BytesIO(payload))
    return output.getvalue()


def _eve_payload() -> dict:
    return {
        "blueprint_ref": "gcp/eve-ng@v1",
        "archive_before_destroy": {
            "module_ref": "platform/linux/eve-ng-lab-archive",
            "state_instance": "gcp_eve_ng_lab_archive",
        },
    }


def _gns3_payload() -> dict:
    return {
        "blueprint_ref": "gcp/gns3@v1",
        "archive_before_destroy": {
            "module_ref": "platform/linux/gns3-lab-archive",
            "state_instance": "gcp_gns3_lab_archive",
            "contract_prefix": "gns3_lab_archive",
        },
    }


class LabMigrationInspectionTest(TestCase):
    def test_inspects_eve_archive_and_node_state(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            archive = Path(tmp) / "eve.tar.gz"
            node_state = Path(tmp) / "nodes.tar.gz"
            _write_tar(
                archive,
                {
                    "0/network.unl": (
                        b'<lab><node name="r1" image="vios-159" /></lab>'
                    )
                },
            )
            _write_tar(node_state, {"0/network/1/virtioa.qcow2": b"overlay"})

            report = inspect_migration_archive(
                platform="eve-ng",
                archive=archive,
                node_state=node_state,
            )

        self.assertEqual(report["status"], "compatible")
        self.assertEqual(report["definition_count"], 1)
        self.assertEqual(report["image_references"], ["vios-159"])
        self.assertGreater(report["archive"]["expanded_size_bytes"], 0)
        self.assertEqual(report["node_state"]["overlay_count"], 1)
        self.assertGreater(report["node_state"]["expanded_size_bytes"], 0)

    def test_rejects_unsafe_archive_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            archive = Path(tmp) / "unsafe.tar.gz"
            _write_tar(archive, {"../network.unl": b"<lab />"})

            with self.assertRaisesRegex(ValueError, "escapes its root"):
                inspect_migration_archive(platform="eve-ng", archive=archive)

    def test_rejects_duplicate_normalised_member(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            archive = Path(tmp) / "duplicate.tar.gz"
            with tarfile.open(archive, mode="w:gz") as handle:
                for name in ("0/network.unl", "./0/network.unl"):
                    payload = b"<lab />"
                    member = tarfile.TarInfo(name=name)
                    member.size = len(payload)
                    handle.addfile(member, io.BytesIO(payload))

            with self.assertRaisesRegex(ValueError, "duplicate member"):
                inspect_migration_archive(platform="eve-ng", archive=archive)

    def test_rejects_eve_archive_with_host_root_prefix(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            archive = Path(tmp) / "eve.tar.gz"
            _write_tar(
                archive,
                {"opt/unetlab/labs/0/network.unl": b"<lab />"},
            )

            with self.assertRaisesRegex(ValueError, "relative to /opt/unetlab/labs"):
                inspect_migration_archive(platform="eve-ng", archive=archive)

    def test_rejects_invalid_eve_node_state_layout(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            archive = Path(tmp) / "eve.tar.gz"
            node_state = Path(tmp) / "nodes.tar.gz"
            _write_tar(archive, {"0/network.unl": b"<lab />"})
            _write_tar(node_state, {"tmp/network/overlay.qcow2": b"overlay"})

            with self.assertRaisesRegex(ValueError, "invalid path"):
                inspect_migration_archive(
                    platform="eve-ng",
                    archive=archive,
                    node_state=node_state,
                )

    def test_inspects_gns3_projects_and_image_references(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            archive = Path(tmp) / "gns3.tar.gz"
            project = json.dumps(
                {
                    "topology": {
                        "nodes": [
                            {"properties": {"hda_disk_image": "vios.qcow2"}}
                        ]
                    }
                }
            ).encode()
            _write_tar(archive, {"projects/lab/project.gns3": project})

            report = inspect_migration_archive(
                platform="gns3",
                archive=archive,
            )

        self.assertEqual(report["definition_count"], 1)
        self.assertEqual(report["image_references"], ["vios.qcow2"])
        self.assertFalse(report["images_included"])

    def test_expected_checksum_is_enforced(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            archive = Path(tmp) / "eve.tar.gz"
            _write_tar(archive, {"0/network.unl": b"<lab />"})

            with self.assertRaisesRegex(ValueError, "does not match"):
                inspect_migration_archive(
                    platform="eve-ng",
                    archive=archive,
                    expected_sha256="a" * 64,
                )


class LabMigrationStagingTest(TestCase):
    def test_stages_and_loads_verified_archive(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            paths = RuntimePaths.from_root(Path(tmp) / "runtime")
            ensure_layout(paths)
            archive = Path(tmp) / "eve.tar.gz"
            node_state = Path(tmp) / "nodes.tar.gz"
            _write_tar(archive, {"0/network.unl": b"<lab />"})
            _write_tar(node_state, {"0/network/1/virtioa.qcow2": b"overlay"})

            record = stage_migration_archive(
                paths=paths,
                payload=_eve_payload(),
                platform="eve-ng",
                archive=archive,
                node_state=node_state,
            )
            loaded = load_migration_archive(paths=paths, payload=_eve_payload())

            self.assertIsNotNone(loaded)
            primary, checksum, node_path, node_checksum = loaded
            self.assertTrue(primary.is_file())
            self.assertTrue(node_path.is_file())
            self.assertEqual(checksum, hashlib.sha256(archive.read_bytes()).hexdigest())
            self.assertEqual(
                node_checksum,
                hashlib.sha256(node_state.read_bytes()).hexdigest(),
            )
            self.assertEqual(record["status"], "verified")
            self.assertTrue(
                migration_record_path(paths, "gcp/eve-ng@v1").is_file()
            )

    def test_import_is_idempotent_for_same_bundle(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            paths = RuntimePaths.from_root(Path(tmp) / "runtime")
            ensure_layout(paths)
            archive = Path(tmp) / "eve.tar.gz"
            _write_tar(archive, {"0/network.unl": b"<lab />"})

            first = stage_migration_archive(
                paths=paths,
                payload=_eve_payload(),
                platform="eve-ng",
                archive=archive,
            )
            second = stage_migration_archive(
                paths=paths,
                payload=_eve_payload(),
                platform="eve-ng",
                archive=archive,
            )

        self.assertEqual(first["archive"]["path"], second["archive"]["path"])

    def test_different_bundle_requires_force(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            paths = RuntimePaths.from_root(Path(tmp) / "runtime")
            ensure_layout(paths)
            first = Path(tmp) / "first.tar.gz"
            second = Path(tmp) / "second.tar.gz"
            _write_tar(first, {"0/first.unl": b"<lab />"})
            _write_tar(second, {"0/second.unl": b"<lab />"})
            stage_migration_archive(
                paths=paths,
                payload=_eve_payload(),
                platform="eve-ng",
                archive=first,
            )

            with self.assertRaisesRegex(ValueError, "already staged"):
                stage_migration_archive(
                    paths=paths,
                    payload=_eve_payload(),
                    platform="eve-ng",
                    archive=second,
                )

    def test_node_state_change_creates_a_new_bundle(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            paths = RuntimePaths.from_root(Path(tmp) / "runtime")
            ensure_layout(paths)
            archive = Path(tmp) / "eve.tar.gz"
            first_node_state = Path(tmp) / "nodes-first.tar.gz"
            second_node_state = Path(tmp) / "nodes-second.tar.gz"
            _write_tar(archive, {"0/network.unl": b"<lab />"})
            _write_tar(
                first_node_state,
                {"0/network/1/virtioa.qcow2": b"first"},
            )
            _write_tar(
                second_node_state,
                {"0/network/1/virtioa.qcow2": b"second"},
            )

            first = stage_migration_archive(
                paths=paths,
                payload=_eve_payload(),
                platform="eve-ng",
                archive=archive,
                node_state=first_node_state,
            )
            second = stage_migration_archive(
                paths=paths,
                payload=_eve_payload(),
                platform="eve-ng",
                archive=archive,
                node_state=second_node_state,
                force=True,
            )

        self.assertNotEqual(first["node_state"]["path"], second["node_state"]["path"])
        self.assertEqual(
            second["supersedes"]["node_state_sha256"],
            first["node_state"]["sha256"],
        )

    def test_platform_must_match_blueprint(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            paths = RuntimePaths.from_root(Path(tmp) / "runtime")
            ensure_layout(paths)
            archive = Path(tmp) / "gns3.tar.gz"
            _write_tar(archive, {"projects/lab/project.gns3": b"{}"})

            with self.assertRaisesRegex(ValueError, "does not match"):
                stage_migration_archive(
                    paths=paths,
                    payload=_eve_payload(),
                    platform="gns3",
                    archive=archive,
                )

    def test_record_outside_artifact_root_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            paths = RuntimePaths.from_root(Path(tmp) / "runtime")
            ensure_layout(paths)
            archive = Path(tmp) / "eve.tar.gz"
            _write_tar(archive, {"0/network.unl": b"<lab />"})
            checksum = hashlib.sha256(archive.read_bytes()).hexdigest()
            record_path = migration_record_path(paths, "gcp/eve-ng@v1")
            record_path.parent.mkdir(parents=True)
            record_path.write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "kind": "hybridops/lab-migration",
                        "status": "verified",
                        "platform": "eve-ng",
                        "blueprint_ref": "gcp/eve-ng@v1",
                        "archive": {"path": str(archive), "sha256": checksum},
                        "node_state": None,
                    }
                ),
                encoding="utf-8",
            )

            with self.assertRaisesRegex(ValueError, "outside"):
                load_migration_archive(paths=paths, payload=_eve_payload())

    def test_gns3_payload_helper_is_valid(self) -> None:
        self.assertEqual(_gns3_payload()["blueprint_ref"], "gcp/gns3@v1")

    def test_import_rejects_insufficient_controller_disk_space(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            paths = RuntimePaths.from_root(Path(tmp) / "runtime")
            ensure_layout(paths)
            archive = Path(tmp) / "eve.tar.gz"
            _write_tar(archive, {"0/network.unl": b"<lab />"})

            with patch(
                "hyops.lab.migration.shutil.disk_usage",
                return_value=SimpleNamespace(free=1),
            ), self.assertRaisesRegex(
                ValueError,
                "insufficient disk space for migration import",
            ):
                stage_migration_archive(
                    paths=paths,
                    payload=_eve_payload(),
                    platform="eve-ng",
                    archive=archive,
                )


class LabMigrationCaptureTest(TestCase):
    def test_captures_eve_archive_and_node_state_over_ssh(self) -> None:
        primary = _tar_bytes({"0/network.unl": b"<lab />"})
        nodes = _tar_bytes({"0/network/1/virtioa.qcow2": b"overlay"})
        streams = iter((primary, nodes))

        def run_capture(argv, *, stdout, stderr, check):
            self.assertEqual(argv[0], "ssh")
            self.assertFalse(check)
            self.assertEqual(stderr, subprocess.PIPE)
            stdout.write(next(streams))
            return subprocess.CompletedProcess(argv, 0, b"", b"")

        with tempfile.TemporaryDirectory() as tmp, patch(
            "hyops.lab.migration.subprocess.run",
            side_effect=run_capture,
        ) as run:
            output = Path(tmp) / "eve.tar.gz"
            report = capture_existing_lab(
                platform="eve-ng",
                host="eve.example.test",
                user="operator",
                output=output,
                include_node_state=True,
            )

            self.assertTrue(output.is_file())
            self.assertTrue(Path(report["node_state"]["path"]).is_file())
            self.assertEqual(report["definition_count"], 1)
            self.assertEqual(run.call_count, 2)
            for call in run.call_args_list:
                remote = call.args[0][-1]
                self.assertNotIn("systemctl stop", remote)
                self.assertNotIn("rm ", remote)

    def test_capture_failure_does_not_publish_partial_output(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, patch(
            "hyops.lab.migration.subprocess.run",
            return_value=subprocess.CompletedProcess(
                ["ssh"],
                21,
                b"",
                b"EVE-NG QEMU nodes are running",
            ),
        ):
            output = Path(tmp) / "eve.tar.gz"
            with self.assertRaisesRegex(ValueError, "nodes are running"):
                capture_existing_lab(
                    platform="eve-ng",
                    host="eve.example.test",
                    output=output,
                )

            self.assertFalse(output.exists())

    def test_capture_translates_late_disk_full_failure(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            candidate = Path(tmp) / "capture.candidate"
            with patch(
                "hyops.lab.migration.subprocess.run",
                return_value=subprocess.CompletedProcess(
                    ["ssh"], 1, b"", b"write failed: No space left on device"
                ),
            ), self.assertRaisesRegex(
                ValueError,
                "output filesystem became full",
            ):
                _capture_stream(["ssh"], candidate)

    def test_capture_rejects_symbolic_link_output(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "target.tar.gz"
            target.write_bytes(b"existing")
            output = Path(tmp) / "eve.tar.gz"
            output.symlink_to(target)

            with self.assertRaisesRegex(ValueError, "symbolic link"):
                capture_existing_lab(
                    platform="eve-ng",
                    host="eve.example.test",
                    output=output,
                    force=True,
                )

            self.assertEqual(target.read_bytes(), b"existing")

    def test_capture_cleans_candidate_when_companion_output_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "eve.tar.gz"
            node_output = Path(tmp) / "nodes.tar.gz"
            node_output.write_bytes(b"existing")

            with self.assertRaisesRegex(ValueError, "output already exists"):
                capture_existing_lab(
                    platform="eve-ng",
                    host="eve.example.test",
                    output=output,
                    include_node_state=True,
                    node_state_output=node_output,
                )

            self.assertFalse(output.exists())
            self.assertEqual(list(Path(tmp).glob("*.candidate")), [])

    def test_gns3_image_capture_is_explicit(self) -> None:
        primary = _tar_bytes({"projects/lab/project.gns3": b"{}"})

        def run_capture(argv, *, stdout, stderr, check):
            stdout.write(primary)
            self.assertIn("images", argv[-1])
            self.assertIn('cd "$root"', argv[-1])
            self.assertIn("Insufficient disk space for lab capture", argv[-1])
            return subprocess.CompletedProcess(argv, 0, b"", b"")

        with tempfile.TemporaryDirectory() as tmp, patch(
            "hyops.lab.migration.subprocess.run",
            side_effect=run_capture,
        ):
            report = capture_existing_lab(
                platform="gns3",
                host="gns3.example.test",
                output=Path(tmp) / "gns3.tar.gz",
                include_images=True,
            )

        self.assertEqual(report["platform"], "gns3")

    def test_capture_reports_insufficient_output_disk_space(self) -> None:
        def reject_capture(argv, *, stdout, stderr, check):
            self.assertIn("Insufficient disk space for lab capture", argv[-1])
            return subprocess.CompletedProcess(
                argv,
                23,
                b"",
                b"Insufficient disk space for lab capture: source requires at least "
                b"1048576 bytes; output filesystem has 1 bytes available",
            )

        with tempfile.TemporaryDirectory() as tmp, patch(
            "hyops.lab.migration.shutil.disk_usage",
            return_value=SimpleNamespace(free=1),
        ), patch(
            "hyops.lab.migration.subprocess.run",
            side_effect=reject_capture,
        ):
            output = Path(tmp) / "eve.tar.gz"
            with self.assertRaisesRegex(
                ValueError,
                "Insufficient disk space for lab capture",
            ):
                capture_existing_lab(
                    platform="eve-ng",
                    host="eve.example.test",
                    output=output,
                )

            self.assertFalse(output.exists())
