import unittest
from unittest.mock import patch

from hyops.drivers.images.packer.driver import (
    _detect_workstation_ip,
    _http_bind_address_is_valid,
)


class _RouteSocket:
    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def connect(self, target):
        self.target = target

    def getsockname(self):
        return ("192.168.0.50", 49152)


class ProxmoxPackerAddressTest(unittest.TestCase):
    def test_detects_operating_system_route_without_ip_command(self):
        route = _RouteSocket()
        with patch("hyops.drivers.images.packer.driver.socket.socket", return_value=route):
            detected = _detect_workstation_ip("192.168.0.27")
        self.assertEqual(detected, "192.168.0.50")
        self.assertEqual(route.target, ("192.168.0.27", 9))

    def test_loopback_is_a_valid_local_bind_address(self):
        self.assertTrue(_http_bind_address_is_valid("127.0.0.1"))

    def test_unassigned_address_is_not_a_valid_bind_address(self):
        self.assertFalse(_http_bind_address_is_valid("192.0.2.123"))

    def test_wildcard_remains_valid(self):
        self.assertTrue(_http_bind_address_is_valid("0.0.0.0"))


if __name__ == "__main__":
    unittest.main()
