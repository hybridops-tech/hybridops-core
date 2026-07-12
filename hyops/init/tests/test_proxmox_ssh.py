import io
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from hyops.init.targets.proxmox import _ensure_bootstrap_ssh_access


class ProxmoxSshOnboardingTest(unittest.TestCase):
    def _values(self, root: Path):
        private_key = root / "id_ed25519"
        public_key = root / "id_ed25519.pub"
        private_key.write_text("private-test-placeholder", encoding="utf-8")
        public_key.write_text("ssh-ed25519 test", encoding="utf-8")
        return {
            "host": "192.0.2.10",
            "ssh_username": "root",
            "ssh_private_key": str(private_key),
            "ssh_public_key": "",
        }

    def test_existing_key_access_needs_no_onboarding(self):
        with tempfile.TemporaryDirectory() as tmp:
            values = self._values(Path(tmp))
            with patch(
                "hyops.init.targets.proxmox.run_capture",
                return_value=SimpleNamespace(rc=0),
            ) as probe:
                result = _ensure_bootstrap_ssh_access(
                    values,
                    evidence_dir=Path(tmp),
                    non_interactive=False,
                )
        self.assertTrue(result)
        self.assertEqual(probe.call_count, 1)

    def test_non_interactive_failure_prints_remediation(self):
        output = io.StringIO()
        with tempfile.TemporaryDirectory() as tmp:
            values = self._values(Path(tmp))
            with (
                patch("hyops.init.targets.proxmox.run_capture", return_value=SimpleNamespace(rc=255)),
                patch("sys.stdout", output),
            ):
                result = _ensure_bootstrap_ssh_access(
                    values,
                    evidence_dir=Path(tmp),
                    non_interactive=True,
                )
        self.assertFalse(result)
        self.assertIn("ssh-copy-id", output.getvalue())
        self.assertIn("run record:", output.getvalue())

    def test_interactive_onboarding_retries_key_access(self):
        with tempfile.TemporaryDirectory() as tmp:
            values = self._values(Path(tmp))
            terminal = io.StringIO()
            terminal.isatty = lambda: True
            with (
                patch(
                    "hyops.init.targets.proxmox.run_capture",
                    side_effect=[SimpleNamespace(rc=255), SimpleNamespace(rc=0)],
                ) as probe,
                patch("hyops.init.targets.proxmox._need_cmd", return_value=True),
                patch("hyops.init.targets.proxmox.sys.stdin", terminal),
                patch("hyops.init.targets.proxmox.sys.stdout", terminal),
                patch("builtins.input", return_value="y"),
                patch(
                    "hyops.init.targets.proxmox.subprocess.run",
                    return_value=SimpleNamespace(returncode=0),
                ) as copy_id,
            ):
                result = _ensure_bootstrap_ssh_access(
                    values,
                    evidence_dir=Path(tmp),
                    non_interactive=False,
                )
        self.assertTrue(result)
        self.assertEqual(probe.call_count, 2)
        copy_id.assert_called_once()

    def test_declining_onboarding_makes_no_remote_change(self):
        with tempfile.TemporaryDirectory() as tmp:
            values = self._values(Path(tmp))
            terminal = io.StringIO()
            terminal.isatty = lambda: True
            with (
                patch("hyops.init.targets.proxmox.run_capture", return_value=SimpleNamespace(rc=255)),
                patch("hyops.init.targets.proxmox._need_cmd", return_value=True),
                patch("hyops.init.targets.proxmox.sys.stdin", terminal),
                patch("hyops.init.targets.proxmox.sys.stdout", terminal),
                patch("builtins.input", return_value="n"),
                patch("hyops.init.targets.proxmox.subprocess.run") as copy_id,
            ):
                result = _ensure_bootstrap_ssh_access(
                    values,
                    evidence_dir=Path(tmp),
                    non_interactive=False,
                )
        self.assertFalse(result)
        copy_id.assert_not_called()


if __name__ == "__main__":
    unittest.main()
