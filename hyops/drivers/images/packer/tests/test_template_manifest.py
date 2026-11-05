"""Test template manifest generation for source provenance."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from hyops.drivers.images.packer.driver import (
    _extract_iso_info_from_pkrvars,
    _create_template_manifest,
)


class TestTemplateManifest(unittest.TestCase):
    """Test template manifest and source provenance functionality."""

    def test_extract_iso_info_from_pkrvars(self) -> None:
        """Test extracting ISO information from packer variable files."""
        with tempfile.TemporaryDirectory() as tmpdir:
            pkrvars_file = Path(tmpdir) / "test.pkrvars.hcl"
            pkrvars_file.write_text(
                '''
iso_file     = "ubuntu-24.04.3-live-server-amd64.iso"
iso_url      = "https://releases.ubuntu.com/noble/ubuntu-24.04.3-live-server-amd64.iso"
iso_checksum = "sha256:c3514bf0056180d09376462a7a1b4f213c1d6e8ea67fae5c25099c6fd3d8274b"
name         = "ubuntu-24.04-template"
''',
                encoding="utf-8",
            )

            checksum, url, filename = _extract_iso_info_from_pkrvars(pkrvars_file)

            self.assertEqual(checksum, "sha256:c3514bf0056180d09376462a7a1b4f213c1d6e8ea67fae5c25099c6fd3d8274b")
            self.assertEqual(url, "https://releases.ubuntu.com/noble/ubuntu-24.04.3-live-server-amd64.iso")
            self.assertEqual(filename, "ubuntu-24.04.3-live-server-amd64.iso")

    def test_extract_iso_info_nonexistent_file(self) -> None:
        """Test extracting from nonexistent file returns empty strings."""
        nonexistent = Path("/nonexistent/path/test.pkrvars.hcl")
        checksum, url, filename = _extract_iso_info_from_pkrvars(nonexistent)

        self.assertEqual(checksum, "")
        self.assertEqual(url, "")
        self.assertEqual(filename, "")

    def test_create_template_manifest(self) -> None:
        """Test creating template manifest with all required fields."""
        manifest = _create_template_manifest(
            template_key="ubuntu-24.04",
            template_name="ubuntu-24.04-template",
            template_vmid=9001,
            source_checksum="sha256:c3514bf0056180d09376462a7a1b4f213c1d6e8ea67fae5c25099c6fd3d8274b",
            source_url="https://releases.ubuntu.com/noble/ubuntu-24.04.3-live-server-amd64.iso",
            source_filename="ubuntu-24.04.3-live-server-amd64.iso",
            profile_ref="onprem-proxmox@v1.0",
            pack_id="onprem/proxmox/images/00-template-image@v1.0",
            builder_version="1.9.4",
            run_id="apply-20261105T200245Z-56cc290f",
        )

        # Verify all fields are present
        self.assertEqual(manifest["template_key"], "ubuntu-24.04")
        self.assertEqual(manifest["template_name"], "ubuntu-24.04-template")
        self.assertEqual(manifest["template_vm_id"], 9001)
        self.assertEqual(
            manifest["source_checksum"],
            "sha256:c3514bf0056180d09376462a7a1b4f213c1d6e8ea67fae5c25099c6fd3d8274b",
        )
        self.assertEqual(
            manifest["source_url"],
            "https://releases.ubuntu.com/noble/ubuntu-24.04.3-live-server-amd64.iso",
        )
        self.assertEqual(manifest["source_filename"], "ubuntu-24.04.3-live-server-amd64.iso")
        self.assertEqual(manifest["profile"], "onprem-proxmox@v1.0")
        self.assertEqual(manifest["pack_id"], "onprem/proxmox/images/00-template-image@v1.0")
        self.assertEqual(manifest["builder_version"], "1.9.4")
        self.assertEqual(manifest["run_id"], "apply-20261105T200245Z-56cc290f")

    def test_manifest_no_credentials(self) -> None:
        """Test that manifest does not contain credentials."""
        manifest = _create_template_manifest(
            template_key="ubuntu-24.04",
            template_name="ubuntu-24.04-template",
            template_vmid=9001,
            source_checksum="sha256:c3514bf0056180d09376462a7a1b4f213c1d6e8ea67fae5c25099c6fd3d8274b",
            source_url="https://releases.ubuntu.com/noble/ubuntu-24.04.3-live-server-amd64.iso",
            source_filename="ubuntu-24.04.3-live-server-amd64.iso",
            profile_ref="onprem-proxmox@v1.0",
            pack_id="onprem/proxmox/images/00-template-image@v1.0",
            builder_version="1.9.4",
            run_id="apply-20261105T200245Z-56cc290f",
        )

        # Verify no credential fields are present
        manifest_str = str(manifest).lower()
        self.assertNotIn("token", manifest_str)
        self.assertNotIn("password", manifest_str)
        self.assertNotIn("secret", manifest_str)
        self.assertNotIn("credential", manifest_str)


if __name__ == "__main__":
    unittest.main()
