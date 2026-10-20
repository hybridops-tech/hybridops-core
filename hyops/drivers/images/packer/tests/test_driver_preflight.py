import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from hyops.drivers.images.packer.driver import run


class PackerDriverPreflightTest(unittest.TestCase):
    def _request(self, root: Path) -> dict:
        credentials_dir = root / "credentials"
        credentials_dir.mkdir(parents=True)
        (credentials_dir / "proxmox.credentials.tfvars").write_text(
            "\n".join(
                [
                    'proxmox_url = "https://pve.example:8006/api2/json"',
                    'proxmox_token_id = "automation@pam!infra-token"',
                    'proxmox_token_secret = "secret"',
                    'proxmox_node = "pve"',
                    'storage_pool = "local-lvm"',
                    'storage_iso = "local"',
                    'network_bridge = "vmbr0"',
                    'http_bind_address = "127.0.0.1"',
                    "http_port = 8802",
                    'ssh_public_key = "ssh-ed25519 test"',
                ]
            ),
            encoding="utf-8",
        )
        return {
            "run_id": "preflight-test",
            "command": "preflight",
            "module_ref": "core/onprem/template-image",
            "inputs": {
                "template_key": "ubuntu-24.04",
                "vmid": 981001,
                "name": "ubuntu-test",
            },
            "execution": {
                "driver": "images/packer",
                "profile": "onprem-proxmox@v1.0",
                "pack_id": "onprem/proxmox/images/00-template-image@v1.0",
            },
            "runtime": {
                "root": str(root),
                "env": "test",
                "work_dir": str(root / "work"),
                "credentials_dir": str(credentials_dir),
            },
            "evidence_dir": str(root / "evidence"),
        }

    def _pack_stack(self) -> SimpleNamespace:
        repo_root = Path(__file__).resolve().parents[5]
        return SimpleNamespace(
            stack_dir=(
                repo_root
                / "packs"
                / "images"
                / "packer"
                / "onprem"
                / "proxmox"
                / "images"
                / "00-template-image@v1.0"
                / "stack"
            )
        )

    @patch("hyops.drivers.images.packer.driver._proxmox_installer_delivery_error")
    @patch("hyops.drivers.images.packer.driver._validate_proxmox_build_readiness")
    @patch("hyops.drivers.images.packer.driver._proxmox_vmid_is_template", return_value=(True, ""))
    @patch("hyops.drivers.images.packer.driver._proxmox_vmid_exists", return_value=(True, ""))
    @patch("hyops.drivers.images.packer.driver.resolve_pack_stack")
    @patch("hyops.drivers.images.packer.driver.shutil.which", return_value="/usr/bin/packer")
    def test_existing_template_skips_build_readiness(
        self,
        _which,
        resolve_pack,
        _vmid_exists,
        _is_template,
        readiness,
        delivery,
    ):
        resolve_pack.return_value = self._pack_stack()
        with tempfile.TemporaryDirectory() as tmp:
            result = run(self._request(Path(tmp)))

        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["normalized_outputs"]["reason"], "template-exists")
        delivery.assert_not_called()
        readiness.assert_not_called()

    @patch("hyops.drivers.images.packer.driver._proxmox_vmid_is_template", return_value=(False, ""))
    @patch("hyops.drivers.images.packer.driver._proxmox_vmid_exists", return_value=(True, ""))
    @patch("hyops.drivers.images.packer.driver.resolve_pack_stack")
    @patch("hyops.drivers.images.packer.driver.shutil.which", return_value="/usr/bin/packer")
    def test_incomplete_vm_is_not_accepted_as_existing_template(
        self,
        _which,
        resolve_pack,
        _vmid_exists,
        _is_template,
    ):
        resolve_pack.return_value = self._pack_stack()
        with tempfile.TemporaryDirectory() as tmp:
            result = run(self._request(Path(tmp)))

        self.assertEqual(result["status"], "error")
        self.assertIn("exists but is not a Proxmox template", result["error"])

    @patch(
        "hyops.drivers.images.packer.driver._validate_proxmox_build_readiness",
        return_value="required ISO is absent: local:iso/ubuntu.iso",
    )
    @patch("hyops.drivers.images.packer.driver._proxmox_vmid_exists", return_value=(False, ""))
    @patch("hyops.drivers.images.packer.driver.resolve_pack_stack")
    @patch("hyops.drivers.images.packer.driver.shutil.which", return_value="/usr/bin/packer")
    def test_new_build_fails_on_readiness_error(
        self,
        _which,
        resolve_pack,
        _vmid_exists,
        readiness,
    ):
        resolve_pack.return_value = self._pack_stack()
        with tempfile.TemporaryDirectory() as tmp:
            result = run(self._request(Path(tmp)))

        self.assertEqual(result["status"], "error")
        self.assertIn("required ISO is absent", result["error"])
        readiness.assert_called_once()

    @patch("hyops.drivers.images.packer.driver._validate_proxmox_build_readiness")
    @patch(
        "hyops.drivers.images.packer.driver._proxmox_installer_delivery_error",
        return_value="Packer HTTP address is inside WSL NAT",
    )
    @patch("hyops.drivers.images.packer.driver._proxmox_vmid_exists", return_value=(False, ""))
    @patch("hyops.drivers.images.packer.driver.resolve_pack_stack")
    @patch("hyops.drivers.images.packer.driver.shutil.which", return_value="/usr/bin/packer")
    def test_new_build_fails_before_readiness_when_delivery_path_is_invalid(
        self,
        _which,
        resolve_pack,
        _vmid_exists,
        _delivery,
        readiness,
    ):
        resolve_pack.return_value = self._pack_stack()
        with tempfile.TemporaryDirectory() as tmp:
            result = run(self._request(Path(tmp)))

        self.assertEqual(result["status"], "error")
        self.assertIn("inside WSL NAT", result["error"])
        readiness.assert_not_called()


if __name__ == "__main__":
    unittest.main()
