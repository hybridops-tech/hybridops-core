from subprocess import DEVNULL
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import patch

from hyops.drivers.config.ansible.driver import _ensure_local_privilege


class AnsibleLocalPrivilegeTest(TestCase):
    def test_remote_execution_does_not_probe_sudo(self) -> None:
        with patch("hyops.drivers.config.ansible.driver.subprocess.run") as run:
            error = _ensure_local_privilege(
                {"local_execution": False, "become": True}
            )
        self.assertEqual(error, "")
        run.assert_not_called()

    def test_cached_local_privilege_is_reused(self) -> None:
        with (
            patch(
                "hyops.drivers.config.ansible.driver.shutil.which",
                return_value="/usr/bin/sudo",
            ),
            patch(
                "hyops.drivers.config.ansible.driver.subprocess.run",
                return_value=SimpleNamespace(returncode=0),
            ) as run,
        ):
            error = _ensure_local_privilege(
                {"local_execution": True, "become": True}
            )
        self.assertEqual(error, "")
        run.assert_called_once_with(
            ["/usr/bin/sudo", "-n", "true"],
            stdin=DEVNULL,
            stdout=DEVNULL,
            stderr=DEVNULL,
            check=False,
        )

    def test_noninteractive_local_privilege_fails_cleanly(self) -> None:
        stdin = SimpleNamespace(isatty=lambda: False)
        with (
            patch(
                "hyops.drivers.config.ansible.driver.shutil.which",
                return_value="/usr/bin/sudo",
            ),
            patch(
                "hyops.drivers.config.ansible.driver.subprocess.run",
                return_value=SimpleNamespace(returncode=1),
            ),
            patch("hyops.drivers.config.ansible.driver.sys.stdin", stdin),
        ):
            error = _ensure_local_privilege(
                {"local_execution": True, "become": True}
            )
        self.assertEqual(
            error,
            "local privileged execution requires an interactive sudo session",
        )
