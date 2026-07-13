"""Tests for private GCP blueprint access helpers."""

from __future__ import annotations

import socket
import unittest

from hyops.blueprint.command import (
    _native_console_status,
    _parse_eve_qemu_console_ports,
    _require_local_ports_available,
    _wait_for_local_port,
)


class BlueprintAccessTests(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
