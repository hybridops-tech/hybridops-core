from __future__ import annotations

import hashlib
import io
import json
import os
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import patch

from hyops.lab.migration import (
    _CONTAINERLAB_CAPTURE_PROGRAM,
    _EVE_IMAGE_CAPTURE_PROGRAM,
    _capture_requirements,
    _capture_stream,
    _format_bytes,
    _remote_capture_assessment_script,
    capture_existing_lab,
    inspect_migration_archive,
    load_migration_archive,
    load_migration_images,
    migration_record_path,
    platform_for_blueprint,
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


def _containerlab_payload() -> dict:
    return {
        "blueprint_ref": "gcp/containerlab@v1",
        "steps": [
            {
                "module_ref": "platform/linux/containerlab-lab",
                "inputs": {
                    "containerlab_lab_topology_relpath": "lab.clab.yml",
                    "containerlab_lab_labdir_base": (
                        "/var/lib/hybridops/containerlab/labdirs"
                    ),
                },
            }
        ],
    }


def _write_containerlab_archive(path: Path, topology: bytes | None = None) -> None:
    topology_payload = topology or (
        b"name: test\ntopology:\n  nodes:\n    r1:\n"
        b"      kind: linux\n      image: alpine:3.20\n"
    )
    topology_checksum = hashlib.sha256(topology_payload).hexdigest()
    manifest = json.dumps(
        {
            "schema": "hybridops.containerlab.recovery/v1",
            "mode": "rebuild",
            "topology_relpath": "lab.clab.yml",
            "topology_sha256": topology_checksum,
            "source_root_included": True,
            "containerlab_version": "0.78.0",
            "image_refs": ["alpine:3.20"],
            "labdir_base": "/var/lib/hybridops/containerlab/labdirs",
            "native_config_save_attempted": True,
            "native_config_save_rc": 0,
            "native_snapshots_requested": False,
            "lab_directory_included": False,
            "additional_paths_count": 0,
        }
    ).encode()
    _write_tar(
        path,
        {
            "containerlab-migration/lab-source/lab.clab.yml": topology_payload,
            "containerlab-migration/hybridops-recovery-manifest.json": manifest,
        },
    )


class LabMigrationInspectionTest(TestCase):
    def test_inspects_eve_archive_and_node_state(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            archive = Path(tmp) / "eve.tar.gz"
            node_state = Path(tmp) / "nodes.tar.gz"
            _write_tar(
                archive,
                {"0/network.unl": (b'<lab><node name="r1" image="vios-159" /></lab>')},
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

    def test_rejects_eve_definition_with_entity_declaration(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            archive = Path(tmp) / "eve.tar.gz"
            _write_tar(
                archive,
                {
                    "0/network.unl": (
                        b"<!DOCTYPE lab [<!ENTITY x \"expanded\">]><lab><node name='&x;' /></lab>"
                    )
                },
            )

            with self.assertRaisesRegex(ValueError, "DTD or entity declaration"):
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

    def test_inspects_referenced_eve_image_companion(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            archive = Path(tmp) / "eve.tar.gz"
            images = Path(tmp) / "images.tar.gz"
            _write_tar(
                archive,
                {
                    "0/network.unl": (
                        b'<lab><node type="qemu" image="vios-159" /></lab>'
                    )
                },
            )
            _write_tar(
                images,
                {"qemu/vios-159/virtioa.qcow2": b"base image"},
            )

            report = inspect_migration_archive(
                platform="eve-ng",
                archive=archive,
                images=images,
            )

        self.assertTrue(report["images_included"])
        self.assertEqual(report["images"]["image_count"], 1)
        self.assertEqual(
            report["warnings"], ["writable QEMU node state is not included"]
        )

    def test_rejects_incomplete_eve_image_companion(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            archive = Path(tmp) / "eve.tar.gz"
            images = Path(tmp) / "images.tar.gz"
            _write_tar(
                archive,
                {
                    "0/network.unl": (
                        b'<lab><node type="qemu" image="vios-159" /></lab>'
                    )
                },
            )
            _write_tar(images, {"qemu/other/virtioa.qcow2": b"base image"})

            with self.assertRaisesRegex(ValueError, "missing a referenced base"):
                inspect_migration_archive(
                    platform="eve-ng",
                    archive=archive,
                    images=images,
                )

    def test_rejects_unreferenced_eve_image_content(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            archive = Path(tmp) / "eve.tar.gz"
            images = Path(tmp) / "images.tar.gz"
            _write_tar(
                archive,
                {"0/network.unl": b'<lab><node type="qemu" image="vios" /></lab>'},
            )
            _write_tar(
                images,
                {
                    "qemu/vios/virtioa.qcow2": b"required",
                    "qemu/other/virtioa.qcow2": b"unreferenced",
                },
            )

            with self.assertRaisesRegex(ValueError, "unreferenced base"):
                inspect_migration_archive(
                    platform="eve-ng",
                    archive=archive,
                    images=images,
                )

    def test_rejects_iol_licence_material(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            archive = Path(tmp) / "eve.tar.gz"
            images = Path(tmp) / "images.tar.gz"
            _write_tar(
                archive,
                {"0/network.unl": b'<lab><node type="iol" image="router.bin" /></lab>'},
            )
            _write_tar(
                images,
                {
                    "iol/bin/router.bin": b"image",
                    "iol/bin/iourc": b"licence",
                },
            )

            with self.assertRaisesRegex(ValueError, "licence material"):
                inspect_migration_archive(
                    platform="eve-ng",
                    archive=archive,
                    images=images,
                )

    def test_rejects_image_under_the_wrong_eve_type_root(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            archive = Path(tmp) / "eve.tar.gz"
            images = Path(tmp) / "images.tar.gz"
            _write_tar(
                archive,
                {"0/network.unl": b'<lab><node type="qemu" image="vios" /></lab>'},
            )
            _write_tar(images, {"iol/bin/vios": b"wrong type"})

            with self.assertRaisesRegex(ValueError, "missing a referenced base"):
                inspect_migration_archive(
                    platform="eve-ng",
                    archive=archive,
                    images=images,
                )

    def test_inspects_gns3_projects_and_image_references(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            archive = Path(tmp) / "gns3.tar.gz"
            project = json.dumps(
                {
                    "topology": {
                        "nodes": [{"properties": {"hda_disk_image": "vios.qcow2"}}]
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

    def test_inspects_containerlab_recovery_bundle(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            archive = Path(tmp) / "containerlab.tar.gz"
            _write_containerlab_archive(archive)

            report = inspect_migration_archive(
                platform="containerlab",
                archive=archive,
            )

        self.assertEqual(report["definition_count"], 1)
        self.assertEqual(report["image_references"], ["alpine:3.20"])
        self.assertEqual(
            report["containerlab"]["topology_relpath"],
            "lab.clab.yml",
        )
        self.assertFalse(report["images_included"])

    def test_rejects_containerlab_topology_checksum_mismatch(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            archive = Path(tmp) / "containerlab.tar.gz"
            _write_containerlab_archive(archive)
            with tarfile.open(archive, mode="r:gz") as source:
                manifest_member = source.getmember(
                    "containerlab-migration/hybridops-recovery-manifest.json"
                )
                manifest = json.loads(source.extractfile(manifest_member).read())
            manifest["topology_sha256"] = "a" * 64
            _write_tar(
                archive,
                {
                    "containerlab-migration/lab-source/lab.clab.yml": b"name: test\n",
                    "containerlab-migration/hybridops-recovery-manifest.json": (
                        json.dumps(manifest).encode()
                    ),
                },
            )

            with self.assertRaisesRegex(ValueError, "checksum does not match"):
                inspect_migration_archive(
                    platform="containerlab",
                    archive=archive,
                )

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
            images = Path(tmp) / "images.tar.gz"
            _write_tar(
                archive,
                {
                    "0/network.unl": (
                        b'<lab><node type="qemu" image="vios-159" /></lab>'
                    )
                },
            )
            _write_tar(node_state, {"0/network/1/virtioa.qcow2": b"overlay"})
            _write_tar(images, {"qemu/vios-159/virtioa.qcow2": b"base"})

            record = stage_migration_archive(
                paths=paths,
                payload=_eve_payload(),
                platform="eve-ng",
                archive=archive,
                node_state=node_state,
                images=images,
            )
            loaded = load_migration_archive(paths=paths, payload=_eve_payload())
            loaded_images = load_migration_images(
                paths=paths,
                payload=_eve_payload(),
            )

            self.assertIsNotNone(loaded)
            (
                primary,
                checksum,
                node_path,
                node_checksum,
                image_path,
                image_checksum,
            ) = loaded
            self.assertTrue(primary.is_file())
            self.assertTrue(node_path.is_file())
            self.assertEqual(checksum, hashlib.sha256(archive.read_bytes()).hexdigest())
            self.assertEqual(
                node_checksum,
                hashlib.sha256(node_state.read_bytes()).hexdigest(),
            )
            self.assertTrue(image_path.is_file())
            self.assertEqual(
                image_checksum,
                hashlib.sha256(images.read_bytes()).hexdigest(),
            )
            self.assertEqual(loaded_images, (image_path, image_checksum))
            self.assertEqual(record["status"], "verified")
            self.assertTrue(migration_record_path(paths, "gcp/eve-ng@v1").is_file())

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

    def test_stages_containerlab_as_latest_recovery(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            paths = RuntimePaths.from_root(Path(tmp) / "runtime")
            ensure_layout(paths)
            archive = Path(tmp) / "containerlab.tar.gz"
            _write_containerlab_archive(archive)

            record = stage_migration_archive(
                paths=paths,
                payload=_containerlab_payload(),
                platform="containerlab",
                archive=archive,
            )

            latest = paths.root / "artifacts/containerlab/recovery/latest.tar.gz"
            self.assertTrue(latest.is_symlink())
            self.assertTrue(latest.resolve().is_file())
            self.assertEqual(
                latest.resolve(),
                Path(record["archive"]["path"]).resolve(),
            )
            self.assertEqual(
                latest.with_name(latest.name + ".sha256").read_text().strip(),
                record["archive"]["sha256"],
            )
            metadata = json.loads(latest.with_name(latest.name + ".json").read_text())
            self.assertEqual(
                metadata["topology_sha256"],
                record["containerlab"]["topology_sha256"],
            )

    def test_containerlab_latest_recovery_replacement_requires_force(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            paths = RuntimePaths.from_root(Path(tmp) / "runtime")
            ensure_layout(paths)
            recovery = paths.root / "artifacts/containerlab/recovery"
            recovery.mkdir(parents=True)
            latest = recovery / "latest.tar.gz"
            latest.write_bytes(b"old archive")
            latest.with_name(latest.name + ".sha256").write_text(
                "a" * 64 + "\n",
                encoding="utf-8",
            )
            latest.with_name(latest.name + ".json").write_text(
                "{}\n",
                encoding="utf-8",
            )
            archive = Path(tmp) / "containerlab.tar.gz"
            _write_containerlab_archive(archive)

            with self.assertRaisesRegex(ValueError, "latest recovery set"):
                stage_migration_archive(
                    paths=paths,
                    payload=_containerlab_payload(),
                    platform="containerlab",
                    archive=archive,
                )

    def test_containerlab_import_requires_matching_topology_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            paths = RuntimePaths.from_root(Path(tmp) / "runtime")
            ensure_layout(paths)
            archive = Path(tmp) / "containerlab.tar.gz"
            _write_containerlab_archive(archive)
            payload = _containerlab_payload()
            payload["steps"][0]["inputs"]["containerlab_lab_topology_relpath"] = (
                "other.clab.yml"
            )

            with self.assertRaisesRegex(ValueError, "topology path does not match"):
                stage_migration_archive(
                    paths=paths,
                    payload=payload,
                    platform="containerlab",
                    archive=archive,
                )

    def test_containerlab_import_requires_matching_labdir_base(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            paths = RuntimePaths.from_root(Path(tmp) / "runtime")
            ensure_layout(paths)
            archive = Path(tmp) / "containerlab.tar.gz"
            _write_containerlab_archive(archive)
            payload = _containerlab_payload()
            payload["steps"][0]["inputs"]["containerlab_lab_labdir_base"] = (
                "/var/lib/containerlab"
            )

            with self.assertRaisesRegex(ValueError, "labdir base does not match"):
                stage_migration_archive(
                    paths=paths,
                    payload=payload,
                    platform="containerlab",
                    archive=archive,
                )

    def test_containerlab_blueprint_platform_is_detected_from_lab_step(self) -> None:
        self.assertEqual(
            platform_for_blueprint(_containerlab_payload()), "containerlab"
        )

    def test_import_rejects_insufficient_controller_disk_space(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            paths = RuntimePaths.from_root(Path(tmp) / "runtime")
            ensure_layout(paths)
            archive = Path(tmp) / "eve.tar.gz"
            _write_tar(archive, {"0/network.unl": b"<lab />"})

            with (
                patch(
                    "hyops.lab.migration.shutil.disk_usage",
                    return_value=SimpleNamespace(free=1),
                ),
                self.assertRaisesRegex(
                    ValueError,
                    "insufficient disk space for migration import",
                ),
            ):
                stage_migration_archive(
                    paths=paths,
                    payload=_eve_payload(),
                    platform="eve-ng",
                    archive=archive,
                )


class LabMigrationCaptureTest(TestCase):
    def test_formats_capacity_for_operator_output(self) -> None:
        self.assertEqual(
            _format_bytes(171627474944),
            "159.8 GiB (171627474944 bytes)",
        )
        self.assertEqual(_format_bytes(11821371392), "11.0 GiB (11821371392 bytes)")

    def test_assessment_reports_both_eve_streams_without_transferring_data(
        self,
    ) -> None:
        script = _remote_capture_assessment_script(
            "eve-ng",
            include_node_state=True,
        )

        self.assertIn("primary_bytes=", script)
        self.assertIn("node_state_bytes=", script)
        self.assertNotIn("tar --", script)

    def test_containerlab_assessment_uses_declared_source(self) -> None:
        script = _remote_capture_assessment_script(
            "containerlab",
            source_root="/srv/labs/demo",
            topology_relpath="lab.clab.yml",
            source_labdir_base="",
            target_labdir_base="/var/lib/hybridops/containerlab/labdirs",
        )

        self.assertIn("/srv/labs/demo", script)
        self.assertIn("primary_bytes=", script)
        self.assertNotIn("tar --", script)

    def test_containerlab_capture_requires_a_source_root(self) -> None:
        with self.assertRaisesRegex(ValueError, "requires --source-root"):
            capture_existing_lab(
                platform="containerlab",
                host="containerlab.example.test",
                output="containerlab.tar.gz",
            )

    def test_containerlab_capture_rejects_image_export(self) -> None:
        with self.assertRaisesRegex(ValueError, "image references"):
            capture_existing_lab(
                platform="containerlab",
                host="containerlab.example.test",
                output="containerlab.tar.gz",
                source_root="/srv/labs/demo",
                include_images=True,
            )

    def test_remote_containerlab_capture_builds_recovery_contract(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "source"
            source.mkdir()
            (source / "lab.clab.yml").write_text(
                "name: test\ntopology:\n  nodes:\n    r1:\n"
                "      kind: linux\n      image: alpine:3.20\n",
                encoding="utf-8",
            )
            runtime = source / "clab-test"
            runtime.mkdir()
            (runtime / "transient").write_text("runtime", encoding="utf-8")

            capture = subprocess.run(
                [
                    sys.executable,
                    "-c",
                    _CONTAINERLAB_CAPTURE_PROGRAM,
                    "capture",
                    str(source),
                    "lab.clab.yml",
                    "",
                    "/var/lib/hybridops/containerlab/labdirs",
                ],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
            )
            self.assertEqual(capture.returncode, 0, capture.stderr.decode())
            archive = Path(tmp) / "containerlab.tar.gz"
            archive.write_bytes(capture.stdout)
            report = inspect_migration_archive(
                platform="containerlab",
                archive=archive,
            )
            with tarfile.open(archive, mode="r:gz") as handle:
                names = handle.getnames()

        self.assertEqual(report["image_references"], ["alpine:3.20"])
        self.assertFalse(any("clab-test" in name for name in names))

    def test_remote_containerlab_capture_merges_native_saved_configs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "source"
            existing_configs = source / "startup-configs"
            existing_configs.mkdir(parents=True)
            (existing_configs / "existing.cfg").write_text(
                "existing\n",
                encoding="utf-8",
            )
            (source / "lab.clab.yml").write_text(
                "name: test\ntopology:\n  nodes:\n    r1:\n"
                "      kind: linux\n      image: alpine:3.20\n",
                encoding="utf-8",
            )
            executable = root / "containerlab"
            executable.write_text(
                "#!/bin/sh\n"
                'case "$1" in\n'
                "  save)\n"
                '    [ "$CLAB_LABDIR_BASE" = '
                '"/srv/containerlab/runtime" ] || exit 9\n'
                "    for destination do :; done\n"
                '    mkdir -p "$destination"\n'
                '    printf "saved\\n" >"$destination/saved.cfg"\n'
                "    ;;\n"
                '  version) printf \'{"version":"0.78.0"}\\n\' ;;\n'
                "  inspect) printf '[]\\n' ;;\n"
                "esac\n",
                encoding="utf-8",
            )
            executable.chmod(0o755)
            environment = dict(os.environ)
            environment["PATH"] = f"{root}:{environment.get('PATH', '')}"

            capture = subprocess.run(
                [
                    sys.executable,
                    "-c",
                    _CONTAINERLAB_CAPTURE_PROGRAM,
                    "capture",
                    str(source),
                    "lab.clab.yml",
                    "/srv/containerlab/runtime",
                    "/var/lib/hybridops/containerlab/labdirs",
                ],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
                env=environment,
            )
            self.assertEqual(capture.returncode, 0, capture.stderr.decode())
            archive = Path(tmp) / "containerlab.tar.gz"
            archive.write_bytes(capture.stdout)
            with tarfile.open(archive, mode="r:gz") as handle:
                names = set(handle.getnames())

        self.assertIn(
            "containerlab-migration/lab-source/startup-configs/existing.cfg",
            names,
        )
        self.assertIn(
            "containerlab-migration/lab-source/startup-configs/saved.cfg",
            names,
        )

    def test_parses_capture_assessment(self) -> None:
        with patch(
            "hyops.lab.migration.subprocess.run",
            return_value=subprocess.CompletedProcess(
                ["ssh"],
                0,
                b"primary_bytes=4096\nnode_state_bytes=8192\nimage_bytes=16384\n",
                b"",
            ),
        ):
            requirements = _capture_requirements(["ssh"])

        self.assertEqual(
            requirements,
            {
                "primary_bytes": 4096,
                "node_state_bytes": 8192,
                "image_bytes": 16384,
            },
        )

    def test_rejects_invalid_capture_assessment(self) -> None:
        with (
            patch(
                "hyops.lab.migration.subprocess.run",
                return_value=subprocess.CompletedProcess(
                    ["ssh"],
                    0,
                    b"primary_bytes=4096\nunexpected=value\n",
                    b"",
                ),
            ),
            self.assertRaisesRegex(ValueError, "invalid output"),
        ):
            _capture_requirements(["ssh"])

    def test_rejects_duplicate_capture_assessment_size(self) -> None:
        with (
            patch(
                "hyops.lab.migration.subprocess.run",
                return_value=subprocess.CompletedProcess(
                    ["ssh"],
                    0,
                    b"primary_bytes=4096\nprimary_bytes=8192\nnode_state_bytes=0\n",
                    b"",
                ),
            ),
            self.assertRaisesRegex(ValueError, "duplicate size"),
        ):
            _capture_requirements(["ssh"])

    def test_captures_eve_archive_and_node_state_over_ssh(self) -> None:
        primary = _tar_bytes({"0/network.unl": b"<lab />"})
        nodes = _tar_bytes({"0/network/1/virtioa.qcow2": b"overlay"})
        streams = iter((primary, nodes))
        progress_events = []

        def run_capture(argv, *, stdout, stderr, check):
            self.assertEqual(argv[0], "ssh")
            self.assertFalse(check)
            self.assertEqual(stderr, subprocess.PIPE)
            stdout.write(next(streams))
            return subprocess.CompletedProcess(argv, 0, b"", b"")

        with (
            tempfile.TemporaryDirectory() as tmp,
            patch(
                "hyops.lab.migration._capture_requirements",
                return_value={
                    "primary_bytes": len(primary),
                    "node_state_bytes": len(nodes),
                    "image_bytes": 0,
                },
            ),
            patch(
                "hyops.lab.migration._close_ssh_control",
            ),
            patch(
                "hyops.lab.migration.subprocess.run",
                side_effect=run_capture,
            ) as run,
        ):
            output = Path(tmp) / "eve.tar.gz"
            report = capture_existing_lab(
                platform="eve-ng",
                host="eve.example.test",
                user="operator",
                output=output,
                include_node_state=True,
                progress=progress_events.append,
            )

            self.assertTrue(output.is_file())
            self.assertTrue(Path(report["node_state"]["path"]).is_file())
            self.assertEqual(report["definition_count"], 1)
            self.assertEqual(run.call_count, 2)
            control_paths = set()
            for call in run.call_args_list:
                control_paths.update(
                    item.split("=", 1)[1]
                    for item in call.args[0]
                    if item.startswith("ControlPath=")
                )
                remote = call.args[0][-1]
                self.assertNotIn("systemctl stop", remote)
                self.assertNotIn("rm ", remote)
            self.assertEqual(len(control_paths), 1)
            self.assertEqual(progress_events[0]["phase"], "assessment_started")
            self.assertEqual(progress_events[1]["phase"], "assessment_finished")
            self.assertEqual(
                [
                    event["stage"]
                    for event in progress_events
                    if event["phase"] == "stream_finished"
                ],
                ["lab_definitions", "node_state"],
            )
            self.assertEqual(progress_events[-1]["phase"], "verification_finished")
            self.assertEqual(progress_events[-1]["status"], "ok")

    def test_capture_failure_does_not_publish_partial_output(self) -> None:
        with (
            tempfile.TemporaryDirectory() as tmp,
            patch(
                "hyops.lab.migration.subprocess.run",
                return_value=subprocess.CompletedProcess(
                    ["ssh"],
                    21,
                    b"",
                    b"EVE-NG QEMU nodes are running",
                ),
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
            with (
                patch(
                    "hyops.lab.migration.subprocess.run",
                    return_value=subprocess.CompletedProcess(
                        ["ssh"], 1, b"", b"write failed: No space left on device"
                    ),
                ),
                self.assertRaisesRegex(
                    ValueError,
                    "output filesystem became full",
                ),
            ):
                _capture_stream(["ssh"], candidate)

    def test_capture_stream_reports_written_bytes(self) -> None:
        events = []
        payload = b"captured archive"

        def run_capture(argv, *, stdout, stderr, check):
            stdout.write(payload)
            return subprocess.CompletedProcess(argv, 0, b"", b"")

        with (
            tempfile.TemporaryDirectory() as tmp,
            patch(
                "hyops.lab.migration.subprocess.run",
                side_effect=run_capture,
            ),
        ):
            candidate = Path(tmp) / "capture.candidate"
            _capture_stream(
                ["ssh"],
                candidate,
                stage="node_state",
                expected_source_bytes=4096,
                progress=events.append,
            )

        self.assertEqual(events[0]["phase"], "stream_started")
        self.assertEqual(events[0]["stage"], "node_state")
        self.assertEqual(events[0]["expected_source_bytes"], 4096)
        self.assertEqual(events[-1]["phase"], "stream_finished")
        self.assertEqual(events[-1]["status"], "ok")
        self.assertEqual(events[-1]["bytes_written"], len(payload))

    def test_capture_translates_remote_capacity_failure(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            candidate = Path(tmp) / "capture.candidate"
            with (
                patch(
                    "hyops.lab.migration.subprocess.run",
                    return_value=subprocess.CompletedProcess(
                        ["ssh"],
                        23,
                        b"",
                        b"Insufficient disk space for lab capture: source requires "
                        b"at least 171627474944 bytes; output filesystem has "
                        b"11821371392 bytes available",
                    ),
                ),
                self.assertRaisesRegex(
                    ValueError,
                    r"159\.8 GiB.*11\.0 GiB",
                ),
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

    def test_captures_referenced_eve_images_as_a_companion(self) -> None:
        primary = _tar_bytes(
            {"0/network.unl": (b'<lab><node type="qemu" image="vios-159" /></lab>')}
        )
        images = _tar_bytes({"qemu/vios-159/virtioa.qcow2": b"base image"})
        streams = iter((primary, images))

        def run_capture(argv, *, stdout, stderr, check):
            stdout.write(next(streams))
            return subprocess.CompletedProcess(argv, 0, b"", b"")

        with (
            tempfile.TemporaryDirectory() as tmp,
            patch(
                "hyops.lab.migration._capture_requirements",
                return_value={
                    "primary_bytes": len(primary),
                    "node_state_bytes": 0,
                    "image_bytes": len(images),
                },
            ),
            patch(
                "hyops.lab.migration._close_ssh_control",
            ),
            patch(
                "hyops.lab.migration.subprocess.run",
                side_effect=run_capture,
            ) as run,
        ):
            output = Path(tmp) / "eve.tar.gz"
            report = capture_existing_lab(
                platform="eve-ng",
                host="eve.example.test",
                output=output,
                include_images=True,
            )

            image_output = Path(report["images"]["path"])
            self.assertTrue(output.is_file())
            self.assertTrue(image_output.is_file())
            self.assertEqual(image_output.name, "eve.images.tar.gz")
            self.assertEqual(report["images"]["image_count"], 1)
            self.assertEqual(run.call_count, 2)

    def test_gns3_image_capture_is_explicit(self) -> None:
        primary = _tar_bytes({"projects/lab/project.gns3": b"{}"})

        def run_capture(argv, *, stdout, stderr, check):
            stdout.write(primary)
            self.assertIn("images", argv[-1])
            self.assertIn('cd "$root"', argv[-1])
            self.assertIn("Insufficient disk space for lab capture", argv[-1])
            return subprocess.CompletedProcess(argv, 0, b"", b"")

        with (
            tempfile.TemporaryDirectory() as tmp,
            patch(
                "hyops.lab.migration._capture_requirements",
                return_value={
                    "primary_bytes": len(primary),
                    "node_state_bytes": 0,
                    "image_bytes": 0,
                },
            ),
            patch(
                "hyops.lab.migration._close_ssh_control",
            ),
            patch(
                "hyops.lab.migration.subprocess.run",
                side_effect=run_capture,
            ),
        ):
            report = capture_existing_lab(
                platform="gns3",
                host="gns3.example.test",
                output=Path(tmp) / "gns3.tar.gz",
                include_images=True,
            )

        self.assertEqual(report["platform"], "gns3")

    def test_capture_reports_insufficient_output_disk_space(self) -> None:
        with (
            tempfile.TemporaryDirectory() as tmp,
            patch(
                "hyops.lab.migration.shutil.disk_usage",
                return_value=SimpleNamespace(free=1),
            ),
            patch(
                "hyops.lab.migration._capture_requirements",
                return_value={
                    "primary_bytes": 1048576,
                    "node_state_bytes": 0,
                    "image_bytes": 0,
                },
            ),
            patch(
                "hyops.lab.migration._close_ssh_control",
            ),
            patch(
                "hyops.lab.migration._capture_stream",
            ) as capture_stream,
        ):
            output = Path(tmp) / "eve.tar.gz"
            with self.assertRaisesRegex(
                ValueError,
                "insufficient disk space for lab capture",
            ):
                capture_existing_lab(
                    platform="eve-ng",
                    host="eve.example.test",
                    output=output,
                )

            self.assertFalse(output.exists())
            capture_stream.assert_not_called()

    def test_remote_eve_image_capture_selects_only_referenced_bases(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            labs = root / "labs"
            addons = root / "addons"
            labs.mkdir()
            (labs / "network.unl").write_text(
                '<lab><node type="qemu" image="vios-159" /></lab>',
                encoding="utf-8",
            )
            selected = addons / "qemu/vios-159"
            selected.mkdir(parents=True)
            (selected / "virtioa.qcow2").write_bytes(b"selected")
            unused = addons / "qemu/unused"
            unused.mkdir(parents=True)
            (unused / "virtioa.qcow2").write_bytes(b"unused")

            assessment = subprocess.run(
                [
                    sys.executable,
                    "-c",
                    _EVE_IMAGE_CAPTURE_PROGRAM,
                    "assess",
                    str(labs),
                    str(addons),
                ],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
            )
            capture = subprocess.run(
                [
                    sys.executable,
                    "-c",
                    _EVE_IMAGE_CAPTURE_PROGRAM,
                    "capture",
                    str(labs),
                    str(addons),
                ],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
            )

            self.assertEqual(assessment.returncode, 0, assessment.stderr.decode())
            self.assertGreater(int(assessment.stdout), 0)
            self.assertEqual(capture.returncode, 0, capture.stderr.decode())
            with tarfile.open(
                fileobj=io.BytesIO(capture.stdout), mode="r:gz"
            ) as handle:
                members = handle.getnames()

        self.assertIn("qemu/vios-159/virtioa.qcow2", members)
        self.assertNotIn("qemu/unused/virtioa.qcow2", members)

    def test_remote_eve_image_capture_rejects_symlinked_lab_definition(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            labs = root / "labs"
            addons = root / "addons"
            labs.mkdir()
            addons.mkdir()
            definition = root / "network.unl"
            definition.write_text("<lab />", encoding="utf-8")
            (labs / "network.unl").symlink_to(definition)

            result = subprocess.run(
                [
                    sys.executable,
                    "-c",
                    _EVE_IMAGE_CAPTURE_PROGRAM,
                    "assess",
                    str(labs),
                    str(addons),
                ],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
            )

        self.assertNotEqual(result.returncode, 0)
        self.assertIn(b"must not be a symbolic link", result.stderr)
