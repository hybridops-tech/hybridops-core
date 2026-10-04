"""Tests for shell installer prerequisites."""

from __future__ import annotations

import subprocess
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
COMMON = REPO_ROOT / "tools" / "install" / "lib" / "common.sh"


def _run_shell(script: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", "-c", f'source "{COMMON}"\n{script}'],
        cwd=REPO_ROOT,
        check=False,
        text=True,
        capture_output=True,
    )


class InstallShellTests(unittest.TestCase):
    def test_administrator_check_accepts_noninteractive_sudo(self) -> None:
        result = _run_shell(
            """
HYOPS_TEST_EUID=1000
exec 3>&1
sudo() {
  printf '%s\\n' "$*" >&3
  [[ "$1" == "-n" ]]
}
hyops_install_administrator_access_ready
"""
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "-n true")

    def test_administrator_check_falls_back_to_interactive_validation(self) -> None:
        result = _run_shell(
            """
HYOPS_TEST_EUID=1000
exec 3>&1
sudo() {
  printf '%s\\n' "$*" >&3
  [[ "$1" == "-v" ]]
}
hyops_install_administrator_access_ready
"""
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.splitlines(), ["-n true", "-v"])

    def test_missing_venv_is_installed_on_apt_hosts(self) -> None:
        result = _run_shell(
            """
ready=0
python3() { [[ "$ready" == "1" ]]; }
uname() { printf '%s\\n' Linux; }
apt-get() { :; }
hyops_install_administrator_access_ready() { return 0; }
hyops_install_run_as_root() {
  printf '%s\\n' "$*"
  [[ "$*" == *"apt-get install -y python3-venv"* ]] && ready=1
  return 0
}
hyops_install_ensure_python_venv
"""
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("apt-get update -y", result.stdout)
        self.assertIn("apt-get install -y python3-venv", result.stdout)

    def test_missing_venv_fails_clearly_on_unsupported_hosts(self) -> None:
        result = _run_shell(
            """
python3() { return 1; }
uname() { printf '%s\\n' Darwin; }
hyops_install_ensure_python_venv
"""
        )

        self.assertEqual(result.returncode, 2)
        self.assertIn("Python virtual environment support is unavailable", result.stderr)


if __name__ == "__main__":
    unittest.main()
