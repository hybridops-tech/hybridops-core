import unittest
from unittest.mock import patch

from hyops.drivers.images.packer.preflight import validate_proxmox_build_readiness
from hyops.drivers.images.packer.proxmox_api import (
    purge_template_vm,
    proxmox_storage_content_exists,
    proxmox_token_has_privilege,
    proxmox_vmid_is_template,
)


BASE_ARGS = {
    "proxmox_url": "https://pve.example:8006/api2/json",
    "proxmox_node": "pve",
    "proxmox_token_id": "automation@pam!infra-token",
    "proxmox_token_secret": "secret",
    "skip_tls": True,
}


class ProxmoxBuildReadinessTest(unittest.TestCase):
    @patch(
        "hyops.drivers.images.packer.preflight.proxmox_token_has_privilege",
        return_value=(False, ""),
    )
    def test_missing_bridge_authority_fails(self, _privilege):
        error = validate_proxmox_build_readiness(
            **BASE_ARGS,
            runtime_vars={"network_bridge": "vmbr0", "storage_iso": "local"},
            base_vars={"iso_file": "ubuntu.iso"},
            env={},
        )

        self.assertIn("lacks SDN.Use", error)
        self.assertIn("/sdn/zones/localnetwork/vmbr0", error)

    @patch(
        "hyops.drivers.images.packer.preflight.proxmox_storage_content_exists",
        return_value=(False, ""),
    )
    @patch(
        "hyops.drivers.images.packer.preflight.proxmox_token_has_privilege",
        return_value=(True, ""),
    )
    def test_missing_cached_iso_fails(self, _privilege, _content):
        error = validate_proxmox_build_readiness(
            **BASE_ARGS,
            runtime_vars={"network_bridge": "vmbr0", "storage_iso": "local"},
            base_vars={"iso_file": "ubuntu.iso"},
            env={},
        )

        self.assertIn("required ISO is absent: local:iso/ubuntu.iso", error)

    @patch(
        "hyops.drivers.images.packer.preflight.proxmox_storage_content_exists",
        return_value=(True, ""),
    )
    @patch(
        "hyops.drivers.images.packer.preflight.proxmox_token_has_privilege",
        return_value=(True, ""),
    )
    def test_cached_iso_passes(self, _privilege, _content):
        error = validate_proxmox_build_readiness(
            **BASE_ARGS,
            runtime_vars={"network_bridge": "vmbr0", "storage_iso": "local"},
            base_vars={"iso_file": "ubuntu.iso"},
            env={},
        )

        self.assertEqual(error, "")

    @patch(
        "hyops.drivers.images.packer.preflight.proxmox_storage_content_exists"
    )
    @patch(
        "hyops.drivers.images.packer.preflight.proxmox_token_has_privilege",
        return_value=(True, ""),
    )
    def test_authorised_download_path_does_not_require_cached_iso(self, _privilege, content):
        error = validate_proxmox_build_readiness(
            **BASE_ARGS,
            runtime_vars={"network_bridge": "vmbr0", "storage_iso": "local"},
            base_vars={
                "iso_file": "ubuntu.iso",
                "iso_url": "https://example.test/ubuntu.iso",
                "iso_checksum": "sha256:abc",
            },
            env={"PKR_VAR_iso_download": "true"},
        )

        self.assertEqual(error, "")
        content.assert_not_called()

    @patch(
        "hyops.drivers.images.packer.preflight.proxmox_storage_content_exists"
    )
    @patch("hyops.drivers.images.packer.preflight.proxmox_token_has_privilege")
    def test_pve_download_requires_network_authority(self, privilege, content):
        privilege.side_effect = [
            (True, ""),
            (True, ""),
            (False, ""),
            (True, ""),
            (False, ""),
        ]

        error = validate_proxmox_build_readiness(
            **BASE_ARGS,
            runtime_vars={"network_bridge": "vmbr0", "storage_iso": "local"},
            base_vars={
                "iso_file": "ubuntu.iso",
                "iso_url": "https://example.test/ubuntu.iso",
                "iso_checksum": "sha256:abc",
            },
            env={
                "PKR_VAR_iso_download": "true",
                "PKR_VAR_iso_download_pve": "true",
            },
        )

        self.assertIn("PVE-side ISO download requires", error)
        content.assert_not_called()


class ProxmoxReadinessApiTest(unittest.TestCase):
    @patch("hyops.drivers.images.packer.proxmox_api.proxmox_request")
    def test_privilege_response_supports_direct_payload(self, request):
        request.return_value = ({"data": {"SDN.Use": 1}}, "")

        allowed, error = proxmox_token_has_privilege(
            proxmox_url=BASE_ARGS["proxmox_url"],
            proxmox_token_id=BASE_ARGS["proxmox_token_id"],
            proxmox_token_secret=BASE_ARGS["proxmox_token_secret"],
            skip_tls=True,
            resource_path="/sdn/zones/localnetwork/vmbr0",
            privilege="SDN.Use",
        )

        self.assertTrue(allowed)
        self.assertEqual(error, "")

    @patch("hyops.drivers.images.packer.proxmox_api.proxmox_request")
    def test_storage_content_requires_exact_volume(self, request):
        request.return_value = (
            {"data": [{"volid": "local:iso/ubuntu.iso"}]},
            "",
        )

        exists, error = proxmox_storage_content_exists(
            proxmox_url=BASE_ARGS["proxmox_url"],
            proxmox_node=BASE_ARGS["proxmox_node"],
            proxmox_token_id=BASE_ARGS["proxmox_token_id"],
            proxmox_token_secret=BASE_ARGS["proxmox_token_secret"],
            skip_tls=True,
            storage="local",
            volume_id="local:iso/ubuntu.iso",
        )

        self.assertTrue(exists)
        self.assertEqual(error, "")

    @patch("hyops.drivers.images.packer.proxmox_api.proxmox_request")
    def test_template_status_uses_proxmox_configuration_flag(self, request):
        request.return_value = ({"data": {"template": 1}}, "")

        is_template, error = proxmox_vmid_is_template(
            **BASE_ARGS,
            vmid=981001,
        )

        self.assertTrue(is_template)
        self.assertEqual(error, "")

    @patch(
        "hyops.drivers.images.packer.proxmox_api.proxmox_vmid_exists",
        return_value=(False, ""),
    )
    @patch("hyops.drivers.images.packer.proxmox_api.proxmox_request")
    def test_purge_uses_resource_label(self, request, _exists):
        request.side_effect = [
            ({"data": {"status": "stopped"}}, ""),
            ({"data": "UPID:test"}, ""),
        ]

        warnings, error = purge_template_vm(
            **BASE_ARGS,
            vmid=981100,
            resource_label="smoke clone",
        )

        self.assertEqual(error, "")
        self.assertIn("purged smoke clone vmid=981100", warnings)


if __name__ == "__main__":
    unittest.main()
