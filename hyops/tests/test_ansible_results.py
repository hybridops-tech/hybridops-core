"""Tests for concise Ansible failure guidance."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from hyops.drivers.config.ansible.results import ansible_error_hint


class AnsibleResultHintTests(unittest.TestCase):
    def test_image_module_reports_mega_transfer_quota(self) -> None:
        for module_ref in (
            "platform/linux/eve-ng-images",
            "platform/linux/gns3-images",
        ):
            with self.subTest(module_ref=module_ref), tempfile.TemporaryDirectory() as tmp:
                evidence_dir = Path(tmp)
                (evidence_dir / "ansible_apply.stdout.txt").write_text(
                    "You have reached your bandwidth quota. Try again later.\n",
                    encoding="utf-8",
                )

                hint = ansible_error_hint(
                    command_name="apply",
                    module_ref=module_ref,
                    inputs={},
                    evidence_dir=evidence_dir,
                    label="ansible_apply",
                )

            self.assertEqual(
                hint,
                "MEGA transfer quota reached. Completed downloads remain cached. "
                "Retry after the quota resets or use another authorised source URL.",
            )

    def test_eve_ng_images_reports_invalid_iourc_document(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            evidence_dir = Path(tmp)
            (evidence_dir / "ansible_apply.stdout.txt").write_text(
                'fatal: [eve-ng-01]: FAILED! => {"msg": "The supplied IOL '
                'licence file is not a valid iourc document."}\n',
                encoding="utf-8",
            )

            hint = ansible_error_hint(
                command_name="apply",
                module_ref="platform/linux/eve-ng-images",
                inputs={},
                evidence_dir=evidence_dir,
                label="ansible_apply",
            )

        self.assertEqual(
            hint,
            "IOL licence content is not a valid iourc document. "
            "Store an authorised iourc with hyops secrets set --from-file, then rerun. "
            "No images were changed.",
        )

    def test_eve_ng_images_reports_iol_hostname_mismatch(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            evidence_dir = Path(tmp)
            (evidence_dir / "ansible_apply.stdout.txt").write_text(
                "fatal: [eve-ng-01]: FAILED! => {\n"
                '  "msg": "The supplied iourc document does not contain a licence entry '
                "for this EVE-NG host. Hostname: platform-labs-eve-ng-01. "
                "FQDN: platform-labs-eve-ng-01.europe-west2-a.c.example.internal. "
                "Host ID: 007f0100. Obtain an authorised iourc for this host, update "
                'EVENG_IOL_LICENSE, and rerun."\n'
                "}\n",
                encoding="utf-8",
            )

            hint = ansible_error_hint(
                command_name="apply",
                module_ref="platform/linux/eve-ng-images",
                inputs={},
                evidence_dir=evidence_dir,
                label="ansible_apply",
            )

        self.assertEqual(
            hint,
            "IOL licence does not match this EVE-NG host. "
            "Hostname: platform-labs-eve-ng-01. Host ID: 007f0100. "
            "Update EVENG_IOL_LICENSE with an authorised iourc for this host, then rerun. "
            "No images were changed.",
        )

    def test_eve_ng_images_accepts_legacy_iol_hostname_mismatch(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            evidence_dir = Path(tmp)
            (evidence_dir / "ansible_apply.stdout.txt").write_text(
                "The supplied iourc document does not contain a licence entry for the "
                "EVE-NG hostname eve-ng-01 or eve-ng-01.example.invalid.",
                encoding="utf-8",
            )

            hint = ansible_error_hint(
                command_name="apply",
                module_ref="platform/linux/eve-ng-images",
                inputs={},
                evidence_dir=evidence_dir,
                label="ansible_apply",
            )

        self.assertEqual(
            hint,
            "IOL licence does not match this EVE-NG host. "
            "Hostname: eve-ng-01. "
            "Update EVENG_IOL_LICENSE with an authorised iourc for this host, then rerun. "
            "No images were changed.",
        )

    def test_gns3_images_reports_iou_hostname_mismatch(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            evidence_dir = Path(tmp)
            (evidence_dir / "ansible_apply.stdout.txt").write_text(
                "fatal: [gns3-01]: FAILED! => {\n"
                '  "msg": "The supplied iourc document does not contain a valid '
                "licence entry for this GNS3 host. Hostname: "
                "platform-gns3-lab-gns3-01. Host ID: 007f0100. Obtain an authorised "
                "iourc for this host, update GNS3_IOU_LICENSE, and rerun.\"\n"
                "}\n",
                encoding="utf-8",
            )

            hint = ansible_error_hint(
                command_name="apply",
                module_ref="platform/linux/gns3-images",
                inputs={},
                evidence_dir=evidence_dir,
                label="ansible_apply",
            )

        self.assertEqual(
            hint,
            "IOU licence does not match this GNS3 host. "
            "Hostname: platform-gns3-lab-gns3-01. Host ID: 007f0100. "
            "Update GNS3_IOU_LICENSE with an authorised iourc for this host, then rerun. "
            "No images were changed.",
        )

    def test_eve_ng_archive_reports_running_nodes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            evidence_dir = Path(tmp)
            (evidence_dir / "ansible_apply.stdout.txt").write_text(
                'fatal: FAILED! "msg": "QEMU nodes are running. '
                'Stop the lab nodes before capturing node state."\n',
                encoding="utf-8",
            )

            hint = ansible_error_hint(
                command_name="apply",
                module_ref="platform/linux/eve-ng-lab-archive",
                inputs={},
                evidence_dir=evidence_dir,
                label="ansible_apply",
            )

        self.assertIn("Stop all active lab nodes", hint)
        self.assertIn("No resources were destroyed", hint)

    def test_eve_ng_archive_reports_existing_image_content(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            evidence_dir = Path(tmp)
            (evidence_dir / "ansible_apply.stdout.txt").write_text(
                'fatal: [eve-ng-01]: FAILED! => {"msg": "EVE-NG image '
                "content already exists at iol/bin/test.bin; use "
                '--overwrite-images only when replacement is intended"}\n',
                encoding="utf-8",
            )

            hint = ansible_error_hint(
                command_name="apply",
                module_ref="platform/linux/eve-ng-lab-archive",
                inputs={},
                evidence_dir=evidence_dir,
                label="ansible_apply",
            )

        self.assertEqual(
            hint,
            "EVE-NG image content already exists at iol/bin/test.bin. "
            "Rerun with --overwrite-images only when replacement is intended.",
        )

    def test_eve_ng_archive_reports_existing_lab_content(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            evidence_dir = Path(tmp)
            (evidence_dir / "ansible_apply.stdout.txt").write_text(
                'fatal: [eve-ng-01]: FAILED! => {"msg": "EVE-NG lab content '
                "already exists at student/lab.unl. Set "
                'eveng_lab_archive_overwrite=true only when replacing it is intended."}\n',
                encoding="utf-8",
            )

            hint = ansible_error_hint(
                command_name="apply",
                module_ref="platform/linux/eve-ng-lab-archive",
                inputs={},
                evidence_dir=evidence_dir,
                label="ansible_apply",
            )

        self.assertEqual(
            hint,
            "EVE-NG lab content already exists at student/lab.unl. "
            "Rerun with --overwrite-labs only when replacement is intended.",
        )

    def test_eve_ng_archive_reports_existing_node_state(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            evidence_dir = Path(tmp)
            (evidence_dir / "ansible_apply.stdout.txt").write_text(
                'fatal: [eve-ng-01]: FAILED! => {"msg": "EVE-NG node state '
                "already exists: 0/lab/1/virtioa.qcow2. Enable overwrite only "
                'when replacement is intended."}\n',
                encoding="utf-8",
            )

            hint = ansible_error_hint(
                command_name="apply",
                module_ref="platform/linux/eve-ng-lab-archive",
                inputs={},
                evidence_dir=evidence_dir,
                label="ansible_apply",
            )

        self.assertEqual(
            hint,
            "EVE-NG node state already exists at 0/lab/1/virtioa.qcow2. "
            "Rerun with --overwrite-labs only when replacement is intended.",
        )


if __name__ == "__main__":
    unittest.main()
