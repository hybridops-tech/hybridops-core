"""Tests for private blueprint access helpers."""

from __future__ import annotations

import io
import socket
import tempfile
import unittest
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from hyops.blueprint.command import (
    _access_known_hosts_file,
    _combine_maintenance,
    _discover_gns3_consoles,
    _extract_access_host,
    _gns3_console_refresher,
    _native_console_refresher,
    _native_console_status,
    _offer_access_close_destroy,
    _parse_eve_qemu_console_ports,
    _print_native_console_client_guidance,
    _require_local_ports_available,
    _runtime_access_secret,
    _ssh_access_error,
    _ssh_access_trust_options,
    _wait_for_local_port,
)
from hyops.runtime.cost import CostEstimate


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

    def test_private_access_trust_is_quiet_and_keeps_verification(self) -> None:
        options = _ssh_access_trust_options(
            Path("/tmp/access.known_hosts"),
            host_key_alias="hyops-eve-ng-01",
        )

        self.assertIn("StrictHostKeyChecking=accept-new", options)
        self.assertIn("UserKnownHostsFile=/tmp/access.known_hosts", options)
        self.assertIn("LogLevel=ERROR", options)
        self.assertIn("HostKeyAlias=hyops-eve-ng-01", options)
        self.assertNotIn("StrictHostKeyChecking=no", options)

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

    def test_empty_console_set_waits_for_active_nodes(self) -> None:
        self.assertEqual(
            _native_console_status([]),
            "native consoles: waiting for active QEMU nodes",
        )

    def test_native_console_refresh_adds_new_qemu_ports(self) -> None:
        proc = Mock()
        proc.poll.return_value = None
        proc.wait.return_value = 0
        with (
            patch(
                "hyops.blueprint.command._discover_eve_qemu_console_ports",
                return_value=[32769, 32770],
            ),
            patch("hyops.blueprint.command._require_local_ports_available"),
            patch("hyops.blueprint.command._wait_for_local_port"),
            patch("hyops.blueprint.command.subprocess.Popen", return_value=proc) as popen,
        ):
            refresh, stop = _native_console_refresher(
                ssh_base=["ssh", "-o", "BatchMode=yes"],
                ssh_target="opsadmin@127.0.0.1",
                known_hosts_file=Path("/tmp/access.known_hosts"),
                forwarded_ports=[32769],
            )
            refresh()
            refresh()
            stop()

        popen.assert_called_once()
        argv = popen.call_args.args[0]
        self.assertIn("127.0.0.1:32770:127.0.0.1:32770", argv)
        self.assertEqual(argv[-1], "opsadmin@127.0.0.1")
        proc.terminate.assert_called_once()

    def test_combined_maintenance_runs_every_callback(self) -> None:
        calls: list[str] = []

        def first() -> None:
            calls.append("first")
            raise RuntimeError("refresh failed")

        def second() -> None:
            calls.append("second")

        combined = _combine_maintenance(first, None, second)
        self.assertIsNotNone(combined)
        with self.assertRaisesRegex(RuntimeError, "refresh failed"):
            combined()
        self.assertEqual(calls, ["first", "second"])

    def test_windows_native_console_guidance_names_host_requirement(self) -> None:
        stdout = io.StringIO()
        with (
            patch("hyops.blueprint.command.is_windows_wsl", return_value=True),
            patch("hyops.blueprint.command.sys.stdout", stdout),
        ):
            _print_native_console_client_guidance("eve-ng-qemu")

        message = stdout.getvalue()
        self.assertIn("EVE-NG Windows Client Pack", message)
        self.assertIn("HTML5 consoles remain available", message)

    def test_native_console_guidance_is_quiet_outside_wsl(self) -> None:
        stdout = io.StringIO()
        with (
            patch("hyops.blueprint.command.is_windows_wsl", return_value=False),
            patch("hyops.blueprint.command.sys.stdout", stdout),
        ):
            _print_native_console_client_guidance("eve-ng-qemu")

        self.assertEqual(stdout.getvalue(), "")

    def test_gns3_console_discovery_uses_controller_local_nodes(self) -> None:
        projects = [{"project_id": "project one"}]
        nodes = [
            {
                "name": "router-1",
                "console": 5000,
                "console_host": "127.0.0.1",
                "console_type": "telnet",
            },
            {
                "name": "desktop-1",
                "console": 5901,
                "console_host": "0.0.0.0",
                "console_type": "vnc",
            },
            {
                "name": "remote-node",
                "console": 5002,
                "console_host": "192.0.2.10",
                "console_type": "telnet",
            },
        ]
        with patch(
            "hyops.blueprint.command._gns3_api_json",
            side_effect=[projects, nodes],
        ) as request:
            consoles = _discover_gns3_consoles(3080, "gns3", "secret")

        self.assertEqual(
            consoles,
            [(5000, "telnet", "router-1"), (5901, "vnc", "desktop-1")],
        )
        self.assertIn("project%20one", request.call_args_list[1].args[0])

    def test_gns3_console_refresh_forwards_each_dynamic_port_once(self) -> None:
        proc = Mock()
        proc.poll.return_value = None
        proc.wait.return_value = 0
        with (
            patch(
                "hyops.blueprint.command._discover_gns3_consoles",
                return_value=[(5000, "telnet", "router-1")],
            ),
            patch("hyops.blueprint.command._require_local_ports_available"),
            patch("hyops.blueprint.command._wait_for_local_port"),
            patch("hyops.blueprint.command.subprocess.Popen", return_value=proc) as popen,
        ):
            refresh, stop = _gns3_console_refresher(
                ssh_base=["ssh", "-o", "BatchMode=yes"],
                ssh_target="opsadmin@127.0.0.1",
                local_api_port=3080,
                username="gns3",
                password="secret",
            )
            refresh()
            refresh()
            stop()

        popen.assert_called_once()
        self.assertIn(
            "127.0.0.1:5000:127.0.0.1:5000",
            popen.call_args.args[0],
        )
        proc.terminate.assert_called_once()

    def test_runtime_console_secret_uses_environment_first(self) -> None:
        paths = SimpleNamespace(vault_dir=Path("/unused"))
        with (
            patch.dict("hyops.blueprint.command.os.environ", {"GNS3_PASSWORD": "value"}),
            patch("hyops.blueprint.command.read_env") as read_env,
        ):
            value = _runtime_access_secret(paths, "lab", "GNS3_PASSWORD")

        self.assertEqual(value, "value")
        read_env.assert_not_called()

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
                cost_estimate=CostEstimate(
                    True,
                    hourly=Decimal("0.50"),
                    currency="USD",
                    basis="public list price",
                ),
                access_started_at=0,
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
        self.assertIn("estimated fixed cost: USD 0.50/hour", stdout.getvalue())
        self.assertIn("estimated access-session cost:", stdout.getvalue())

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
