"""Tests for operator browser integration."""

from __future__ import annotations

import unittest
from unittest.mock import Mock, patch

from hyops.runtime.browser import is_windows_wsl, open_operator_url


class BrowserTests(unittest.TestCase):
    @patch("hyops.runtime.browser.platform.system", return_value="Linux")
    def test_detects_wsl_from_environment(self, _system: Mock) -> None:
        self.assertTrue(
            is_windows_wsl(environ={"WSL_DISTRO_NAME": "Ubuntu"}, kernel_release="6.6.0")
        )

    @patch("hyops.runtime.browser.platform.system", return_value="Linux")
    def test_detects_wsl_from_kernel_release(self, _system: Mock) -> None:
        self.assertTrue(
            is_windows_wsl(
                environ={}, kernel_release="5.15.167.4-microsoft-standard-WSL2"
            )
        )

    @patch("hyops.runtime.browser.platform.system", return_value="Linux")
    def test_plain_linux_is_not_wsl(self, _system: Mock) -> None:
        self.assertFalse(is_windows_wsl(environ={}, kernel_release="6.8.0-generic"))

    @patch("hyops.runtime.browser.subprocess.Popen")
    @patch("hyops.runtime.browser.shutil.which")
    @patch("hyops.runtime.browser.is_windows_wsl", return_value=True)
    def test_wsl_opens_url_with_host_bridge(
        self, _is_wsl: Mock, which: Mock, popen: Mock
    ) -> None:
        which.side_effect = (
            lambda command: f"/usr/bin/{command}" if command == "wslview" else None
        )

        self.assertTrue(open_operator_url("http://127.0.0.1:8080/"))

        popen.assert_called_once()
        self.assertEqual(
            popen.call_args.args[0],
            ["/usr/bin/wslview", "http://127.0.0.1:8080/"],
        )

    @patch("hyops.runtime.browser.webbrowser.open", return_value=True)
    @patch("hyops.runtime.browser.is_windows_wsl", return_value=False)
    def test_non_wsl_uses_python_browser(self, _is_wsl: Mock, browser_open: Mock) -> None:
        self.assertTrue(open_operator_url("https://example.invalid/", new=2))
        browser_open.assert_called_once_with("https://example.invalid/", new=2)


if __name__ == "__main__":
    unittest.main()
