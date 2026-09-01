from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import patch

from hyops.drivers.config.ansible.connectivity import connectivity_check, probe_ssh_auth
from hyops.drivers.config.ansible.inventory import write_inventory


class AnsibleConnectivityTests(TestCase):
    def test_gcp_iap_inventory_disables_ssh_multiplexing(self) -> None:
        with TemporaryDirectory() as tmp:
            inventory = Path(tmp) / "inventory.ini"
            error = write_inventory(
                inventory,
                {
                    "target_user": "opsadmin",
                    "ssh_access_mode": "gcp-iap",
                    "inventory_groups": {
                        "targets": [
                            {
                                "name": "eve-ng-01",
                                "host": "10.80.50.2",
                                "gcp_iap_instance": "eve-ng-01",
                                "gcp_iap_project_id": "project-1",
                                "gcp_iap_zone": "europe-west2-b",
                            }
                        ]
                    },
                },
            )

            self.assertEqual(error, "")
            rendered = inventory.read_text(encoding="utf-8")
            self.assertIn("ansible_ssh_args='-o ControlMaster=no -o ControlPath=none'", rendered)
            self.assertIn("-o ServerAliveInterval=15", rendered)
            self.assertIn("-o ServerAliveCountMax=2", rendered)

    @patch("hyops.drivers.config.ansible.connectivity.run_capture")
    @patch("hyops.drivers.config.ansible.connectivity.shutil.which")
    def test_ssh_probe_checks_passwordless_become(self, which, run_capture) -> None:
        which.side_effect = lambda command: f"/usr/bin/{command}"
        run_capture.return_value = SimpleNamespace(rc=0, stdout="", stderr="")

        ok, error = probe_ssh_auth(
            target_host="10.80.50.2",
            target_user="opsadmin",
            target_port=22,
            ssh_private_key_file="/tmp/id_ed25519",
            proxy_host="",
            proxy_user="",
            proxy_port=0,
            timeout_s=5,
            cwd="/tmp",
            env={},
            evidence_dir=Path("/tmp/evidence"),
            redact=True,
            label="connectivity",
            become=True,
            become_user="root",
        )

        self.assertTrue(ok)
        self.assertEqual(error, "")
        argv = run_capture.call_args.args[0]
        self.assertEqual(argv[-1], "sudo -n -u root true")

    @patch("hyops.drivers.config.ansible.connectivity.probe_ssh_auth")
    def test_connectivity_passes_become_contract_to_probe(self, probe) -> None:
        probe.return_value = (True, "")
        with TemporaryDirectory() as tmp:
            ok, error = connectivity_check(
                command_name="apply",
                inputs={
                    "target_user": "opsadmin",
                    "become": True,
                    "become_user": "root",
                    "ssh_access_mode": "gcp-iap",
                    "inventory_groups": {
                        "targets": [
                            {
                                "name": "eve-ng-01",
                                "host": "10.80.50.2",
                                "gcp_iap_instance": "eve-ng-01",
                                "gcp_iap_project_id": "project-1",
                                "gcp_iap_zone": "europe-west2-b",
                            }
                        ]
                    },
                },
                runtime_root=Path(tmp),
                cwd=tmp,
                env={},
                evidence_dir=Path(tmp) / "evidence",
                redact=True,
            )

        self.assertTrue(ok)
        self.assertEqual(error, "")
        self.assertTrue(probe.call_args.kwargs["become"])
        self.assertEqual(probe.call_args.kwargs["become_user"], "root")

