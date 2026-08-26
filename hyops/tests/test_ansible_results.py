"""Tests for concise Ansible failure guidance."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from hyops.drivers.config.ansible.results import ansible_error_hint


class AnsibleResultHintTests(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
