"""Tests for concise Ansible failure guidance."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from hyops.drivers.config.ansible.results import ansible_error_hint


class AnsibleResultHintTests(unittest.TestCase):
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
