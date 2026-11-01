from __future__ import annotations

import os
import platform
import shlex
import subprocess
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import patch

from hyops.drivers.config.ansible.connectivity import (
    connectivity_check,
    probe_ssh_auth,
    rke2_image_preflight_check,
)
from hyops.drivers.config.ansible.inventory import write_inventory


class AnsibleConnectivityTests(TestCase):
    @patch("hyops.drivers.config.ansible.connectivity.run_capture")
    @patch("hyops.drivers.config.ansible.connectivity.shutil.which")
    def test_rke2_preflight_loads_selected_release_image_list(self, which, run_capture) -> None:
        which.return_value = "/usr/bin/ssh"
        run_capture.return_value = SimpleNamespace(rc=0, stdout="", stderr="")

        ok, error = rke2_image_preflight_check(
            command_name="preflight",
            module_ref="platform/onprem/rke2-cluster",
            inputs={
                "target_user": "opsadmin",
                "inventory_groups": {
                    "rke2_servers": [{"name": "rke2-cp-01", "host": "192.0.2.10"}]
                },
                "rke2_install_version": "v1.34.12+rke2r1",
            },
            cwd="/tmp",
            env={},
            evidence_dir=Path("/tmp/evidence"),
            redact=True,
        )

        self.assertTrue(ok)
        self.assertEqual(error, "")
        remote_command = run_capture.call_args.args[0][-1]
        self.assertIn("RKE2_VERSION=v1.34.12+rke2r1", remote_command)
        self.assertIn('f"{release_tag}/rke2-images.linux-{architecture}.txt"', remote_command)

        remote_script = shlex.split(remote_command)[-1]
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            architecture = {
                "aarch64": "arm64",
                "amd64": "amd64",
                "arm64": "arm64",
                "x86_64": "amd64",
            }[platform.machine().lower()]
            release_dir = root / "releases" / "v1.34.12+rke2r1"
            release_dir.mkdir(parents=True)
            (release_dir / f"rke2-images.linux-{architecture}.txt").write_text(
                "\n".join(
                    (
                        "docker.io/rancher/rke2-runtime:v1.34.12-rke2r1",
                        "docker.io/rancher/hardened-kubernetes:v1.34.12-rke2r1-build1",
                    )
                )
                + "\n",
                encoding="utf-8",
            )
            bin_dir = root / "bin"
            bin_dir.mkdir()
            sudo = bin_dir / "sudo"
            sudo.write_text('#!/bin/sh\nexec "$@"\n', encoding="utf-8")
            sudo.chmod(0o755)

            test_script = remote_script.replace(
                "/etc/rancher/rke2/registries.yaml", str(root / "registries.yaml")
            ).replace(
                "https://github.com/rancher/rke2/releases/download",
                (root / "releases").as_uri(),
            )
            refs_script = test_script.split('\npython3 - "$refs_file"', maxsplit=1)[0]
            refs_script += '\ncat "$refs_file"\n'
            test_env = {
                **os.environ,
                "PATH": f"{bin_dir}:{os.environ['PATH']}",
                "RKE2_VERSION": "v1.34.12+rke2r1",
            }
            result = subprocess.run(
                ["/bin/bash", "-c", refs_script],
                check=True,
                capture_output=True,
                text=True,
                env=test_env,
            )

            (root / "registries.yaml").write_text("mirrors: {}\n", encoding="utf-8")
            registry_result = subprocess.run(
                ["/bin/bash", "-c", test_script],
                check=True,
                capture_output=True,
                text=True,
                env=test_env,
            )

        self.assertIn("docker.io/rancher/rke2-runtime:v1.34.12-rke2r1", result.stdout)
        self.assertIn(
            "docker.io/rancher/hardened-kubernetes:v1.34.12-rke2r1-build1",
            result.stdout,
        )
        self.assertEqual(registry_result.stdout.strip(), '{"skipped":"configured_registry"}')

    @patch("hyops.drivers.config.ansible.connectivity.run_capture")
    @patch("hyops.drivers.config.ansible.connectivity.shutil.which")
    def test_rke2_preflight_uses_trimmed_legacy_version(self, which, run_capture) -> None:
        which.return_value = "/usr/bin/ssh"
        run_capture.return_value = SimpleNamespace(rc=0, stdout="", stderr="")

        ok, error = rke2_image_preflight_check(
            command_name="preflight",
            module_ref="platform/onprem/rke2-cluster",
            inputs={
                "target_user": "opsadmin",
                "inventory_groups": {
                    "rke2_servers": [{"name": "rke2-cp-01", "host": "192.0.2.10"}]
                },
                "rke2_install_version": "  ",
                "rke2_role_vars": {"install_rke2_version": " v1.34.11+rke2r1 "},
            },
            cwd="/tmp",
            env={},
            evidence_dir=Path("/tmp/evidence"),
            redact=True,
        )

        self.assertTrue(ok)
        self.assertEqual(error, "")
        self.assertIn("RKE2_VERSION=v1.34.11+rke2r1", run_capture.call_args.args[0][-1])

    @patch("hyops.drivers.config.ansible.connectivity.run_capture")
    @patch("hyops.drivers.config.ansible.connectivity.shutil.which")
    def test_rke2_preflight_reports_unavailable_release_list(self, which, run_capture) -> None:
        which.return_value = "/usr/bin/ssh"
        run_capture.return_value = SimpleNamespace(
            rc=14,
            stdout='{"error":"release_image_list_unavailable"}',
            stderr="",
        )

        ok, error = rke2_image_preflight_check(
            command_name="preflight",
            module_ref="platform/onprem/rke2-cluster",
            inputs={
                "inventory_groups": {
                    "rke2_servers": [{"name": "rke2-cp-01", "host": "192.0.2.10"}]
                },
                "rke2_install_version": "v1.34.12+rke2r1",
            },
            cwd="/tmp",
            env={},
            evidence_dir=Path("/tmp/evidence"),
            redact=True,
        )

        self.assertFalse(ok)
        self.assertIn("could not load the selected release image list", error)
        self.assertIn("release_image_list_unavailable", error)

    @patch("hyops.drivers.config.ansible.connectivity.run_capture")
    @patch("hyops.drivers.config.ansible.connectivity.shutil.which")
    def test_rke2_preflight_defers_to_declared_registry_config(self, which, run_capture) -> None:
        ok, error = rke2_image_preflight_check(
            command_name="preflight",
            module_ref="platform/onprem/rke2-cluster",
            inputs={
                "rke2_install_version": "v1.34.12+rke2r1",
                "rke2_role_vars": {
                    "registry_config_file_path": "/etc/rancher/rke2/registries.yaml"
                },
            },
            cwd="/tmp",
            env={},
            evidence_dir=Path("/tmp/evidence"),
            redact=True,
        )

        self.assertTrue(ok)
        self.assertEqual(error, "")
        which.assert_not_called()
        run_capture.assert_not_called()

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

