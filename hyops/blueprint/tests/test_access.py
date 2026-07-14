"""Tests for private blueprint access helpers."""

from __future__ import annotations

import io
import socket
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from hyops.blueprint.command import (
    _access_known_hosts_file,
    _extract_access_host,
    _native_console_status,
    _offer_access_close_destroy,
    _parse_eve_qemu_console_ports,
    _require_local_ports_available,
    _ssh_access_error,
    _wait_for_local_port,
)


class _TTY(io.StringIO):
    def isatty(self) -> bool:
        return True


class BlueprintAccessTests(unittest.TestCase):
    def test_host_key_alarm_is_replaced_with_operator_guidance(self) -> None:
        message = _ssh_access_error(
            "WARNING: REMOTE HOST IDENTIFICATION HAS CHANGED!\nHost key verification failed.",
            Path("/tmp/access.known_hosts"),
        )
        self.assertNotIn("SOMEONE", message)
        self.assertNotIn("REMOTE HOST IDENTIFICATION", message)
        self.assertIn("SSH host identity changed unexpectedly", message)
        self.assertIn("/tmp/access.known_hosts", message)

    def test_known_hosts_is_scoped_to_vm_state_run(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = _access_known_hosts_file(
                SimpleNamespace(meta_dir=Path(tmp) / "meta"),
                "platform/onprem/platform-vm#eve_ng_vm",
                {"run_id": "apply-20260712T120000Z-abcd1234"},
            )
            self.assertEqual(path.parent.name, "access_known_hosts")
            self.assertIn("eve_ng_vm-apply-20260712T120000Z-abcd1234", path.name)
            self.assertTrue(path.parent.is_dir())

    def test_extracts_direct_host_from_proxmox_vm_outputs(self) -> None:
        outputs = {
            "vms": {"eve-ng-01": {"ipv4_configured_primary": "192.168.0.84/24"}}
        }
        self.assertEqual(_extract_access_host(outputs), "192.168.0.84")

    def test_extracts_direct_host_from_published_address_map(self) -> None:
        outputs = {"ipv4_addresses": {"eve-ng-01": "192.168.0.84"}}
        self.assertEqual(_extract_access_host(outputs), "192.168.0.84")

    def test_ignores_dhcp_declaration_and_uses_observed_address(self) -> None:
        outputs = {
            "ipv4_addresses": {"eve-ng-01": "dhcp"},
            "ipv4_addresses_all": {"eve-ng-01": ["192.168.0.102"]},
            "vms": {
                "eve-ng-01": {
                    "ipv4_configured_primary": "dhcp",
                    "ipv4_addresses": ["192.168.0.102"],
                }
            },
        }
        self.assertEqual(_extract_access_host(outputs), "192.168.0.102")

    def test_dhcp_without_observed_address_is_not_a_host(self) -> None:
        outputs = {
            "ipv4_addresses": {"eve-ng-01": "dhcp"},
            "vms": {"eve-ng-01": {"ipv4_configured_primary": "dhcp"}},
        }
        self.assertEqual(_extract_access_host(outputs), "")

    def test_parses_active_qemu_ports_without_fixed_range(self) -> None:
        output = """
LISTEN 0 1 0.0.0.0:32770 0.0.0.0:* users:(("qemu-system-x86",pid=2,fd=20))
LISTEN 0 1 0.0.0.0:32769 0.0.0.0:* users:(("qemu-system-x86",pid=1,fd=20))
LISTEN 0 128 0.0.0.0:22 0.0.0.0:* users:(("sshd",pid=3,fd=3))
LISTEN 0 1 [::]:32769 [::]:* users:(("qemu-system-x86",pid=1,fd=21))
"""
        self.assertEqual(_parse_eve_qemu_console_ports(output), [32769, 32770])

    def test_empty_console_set_keeps_web_access_available(self) -> None:
        self.assertEqual(
            _native_console_status([]),
            "native consoles: no active QEMU nodes; web access remains available",
        )

    def test_rejects_local_console_port_conflict(self) -> None:
        listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        listener.bind(("127.0.0.1", 0))
        try:
            with self.assertRaisesRegex(ValueError, "is unavailable on localhost"):
                _require_local_ports_available([listener.getsockname()[1]])
        finally:
            listener.close()

    def test_wait_detects_listener_without_connecting(self) -> None:
        listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        listener.bind(("127.0.0.1", 0))
        listener.listen(1)

        class _Proc:
            returncode = None

            @staticmethod
            def poll():
                return None

        try:
            _wait_for_local_port(listener.getsockname()[1], _Proc(), timeout_s=0.2)
            listener.settimeout(0.05)
            with self.assertRaises(TimeoutError):
                listener.accept()
        finally:
            listener.close()

    def test_access_close_destroy_requires_environment_phrase(self) -> None:
        ns = SimpleNamespace(env="student-lab", root=None, ref="gcp/eve-ng@v1")
        stdout = _TTY()
        payload = {
            "blueprint_ref": "gcp/eve-ng@v1",
            "access": {"offer_destroy_on_close": True},
        }
        with (
            patch("hyops.blueprint.command.sys.stdin", _TTY()),
            patch("hyops.blueprint.command.sys.stdout", stdout),
            patch(
                "hyops.blueprint.command.diagnose_project_billing",
                return_value=(True, True, ""),
            ),
            patch("hyops.blueprint.command.run_destroy", return_value=0) as destroy,
        ):
            rc = _offer_access_close_destroy(
                ns,
                payload,
                {"updated_at": "2026-07-14T08:00:00Z"},
                project_id="student-project",
            )

        self.assertEqual(rc, 0)
        destroy.assert_called_once()
        destroy_ns = destroy.call_args.args[0]
        self.assertTrue(destroy_ns.execute)
        self.assertFalse(destroy_ns.yes)
        self.assertFalse(destroy_ns.archive_before_destroy)
        self.assertFalse(destroy_ns.skip_archive)
        self.assertIn(
            "https://console.cloud.google.com/billing?project=student-project",
            stdout.getvalue(),
        )

    def test_access_close_destroy_delegates_confirmation(self) -> None:
        ns = SimpleNamespace(env="student-lab")
        payload = {
            "blueprint_ref": "gcp/eve-ng@v1",
            "access": {"offer_destroy_on_close": True},
        }
        with (
            patch("hyops.blueprint.command.sys.stdin", _TTY()),
            patch("hyops.blueprint.command.sys.stdout", _TTY()),
            patch("hyops.blueprint.command.run_destroy", return_value=0) as destroy,
        ):
            rc = _offer_access_close_destroy(ns, payload, {})

        self.assertEqual(rc, 0)
        destroy.assert_called_once()


if __name__ == "__main__":
    unittest.main()
