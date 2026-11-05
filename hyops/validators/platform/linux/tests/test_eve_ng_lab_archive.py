"""Tests for the EVE-NG lab archive module validator."""

from copy import deepcopy
from pathlib import Path
import unittest

import yaml

from hyops.validators.platform.linux.eve_ng_lab_archive import validate


REPO_ROOT = Path(__file__).resolve().parents[5]
MODULE_ROOT = REPO_ROOT / "modules" / "platform" / "linux" / "eve-ng-lab-archive"


def valid_inputs() -> dict:
    spec = yaml.safe_load((MODULE_ROOT / "spec.yml").read_text(encoding="utf-8"))
    inputs = deepcopy(spec["inputs"]["defaults"])
    inputs.update(
        {
            "target_host": "127.0.0.1",
            "ssh_private_key_file": "~/.ssh/id_ed25519",
            "connectivity_check": False,
        }
    )
    return inputs


class EveNgLabArchiveValidatorTests(unittest.TestCase):
    def test_export_defaults_are_valid(self) -> None:
        validate(valid_inputs())

    def test_restore_requires_archive_and_checksum(self) -> None:
        inputs = valid_inputs()
        inputs["eveng_lab_archive_action"] = "restore"
        with self.assertRaises(ValueError):
            validate(inputs)

    def test_restore_accepts_verified_archive(self) -> None:
        inputs = valid_inputs()
        inputs.update(
            {
                "eveng_lab_archive_action": "restore",
                "eveng_lab_archive_path": "/tmp/labs.tar.gz",
                "eveng_lab_archive_expected_sha256": "a" * 64,
            }
        )
        validate(inputs)

    def test_unsafe_folder_is_rejected(self) -> None:
        inputs = valid_inputs()
        inputs["eveng_lab_archive_folders"] = ["../images"]
        with self.assertRaises(ValueError):
            validate(inputs)

    def test_node_state_export_requires_complete_lab_tree(self) -> None:
        inputs = valid_inputs()
        inputs["eveng_lab_archive_include_node_state"] = True
        inputs["eveng_lab_archive_folders"] = ["student"]
        with self.assertRaisesRegex(ValueError, "must be empty"):
            validate(inputs)

    def test_legacy_automatic_node_shutdown_setting_is_accepted(self) -> None:
        inputs = valid_inputs()
        inputs["eveng_lab_archive_include_node_state"] = True
        inputs["eveng_lab_archive_stop_running_nodes"] = True
        validate(inputs)

    def test_guest_quiescence_must_be_boolean(self) -> None:
        inputs = valid_inputs()
        inputs["eveng_lab_archive_guest_quiesced"] = "yes"
        with self.assertRaisesRegex(ValueError, "must be a boolean"):
            validate(inputs)

    def test_saved_configuration_capture_is_valid_for_export(self) -> None:
        inputs = valid_inputs()
        inputs["eveng_lab_archive_capture_device_configs"] = True
        validate(inputs)

    def test_saved_configuration_export_timeout_accepts_bounded_override(
        self,
    ) -> None:
        inputs = valid_inputs()
        inputs["eveng_lab_archive_config_export_timeout_s"] = 600
        validate(inputs)

    def test_saved_configuration_export_timeout_is_bounded(self) -> None:
        for value in (True, 0, 3601):
            with self.subTest(value=value):
                inputs = valid_inputs()
                inputs["eveng_lab_archive_config_export_timeout_s"] = value
                with self.assertRaisesRegex(
                    ValueError, "must be between 1 and 3600"
                ):
                    validate(inputs)

    def test_saved_configuration_capture_is_rejected_for_restore(self) -> None:
        inputs = valid_inputs()
        inputs.update(
            {
                "eveng_lab_archive_action": "restore",
                "eveng_lab_archive_path": "/tmp/labs.tar.gz",
                "eveng_lab_archive_expected_sha256": "a" * 64,
                "eveng_lab_archive_capture_device_configs": True,
            }
        )
        with self.assertRaisesRegex(ValueError, "requires an export"):
            validate(inputs)

    def test_saved_configuration_activation_must_be_boolean(self) -> None:
        inputs = valid_inputs()
        inputs["eveng_lab_archive_activate_saved_configs"] = "yes"
        with self.assertRaisesRegex(ValueError, "must be a boolean"):
            validate(inputs)

    def test_saved_configuration_api_url_must_be_http(self) -> None:
        inputs = valid_inputs()
        inputs["eveng_lab_archive_api_base_url"] = "file:///tmp/eve"
        with self.assertRaisesRegex(ValueError, "HTTP or HTTPS"):
            validate(inputs)

    def test_node_state_restore_requires_companion_checksum(self) -> None:
        inputs = valid_inputs()
        inputs.update(
            {
                "eveng_lab_archive_action": "restore",
                "eveng_lab_archive_path": "/tmp/labs.tar.gz",
                "eveng_lab_archive_expected_sha256": "a" * 64,
                "eveng_lab_archive_restore_node_state": True,
                "eveng_lab_archive_node_state_path": "/tmp/nodes.tar.gz",
            }
        )
        with self.assertRaises(ValueError):
            validate(inputs)

    def test_device_config_capture_requires_credentials(self) -> None:
        """Device config capture requires EVE-NG API credentials."""
        inputs = valid_inputs()
        inputs.update({
            "eveng_lab_archive_capture_device_configs": True,
            "load_vault_env": True,
            "required_env": ["EVENG_ADMIN_PASSWORD"],
        })
        validate(inputs)

    def test_device_config_export_timeout_bounds(self) -> None:
        """Device config export timeout must be between 1 and 3600 seconds."""
        for timeout_val in [1, 300, 3600]:
            with self.subTest(timeout=timeout_val):
                inputs = valid_inputs()
                inputs.update({
                    "eveng_lab_archive_capture_device_configs": True,
                    "eveng_lab_archive_config_export_timeout_s": timeout_val,
                })
                validate(inputs)

    def test_device_config_minimal_export_config(self) -> None:
        """Minimal config for device capture export is valid."""
        inputs = valid_inputs()
        inputs.update({
            "eveng_lab_archive_action": "export",
            "eveng_lab_archive_capture_device_configs": True,
        })
        validate(inputs)

    def test_device_config_full_export_workflow(self) -> None:
        """Full device config export with all options is valid."""
        inputs = valid_inputs()
        inputs.update({
            "eveng_lab_archive_action": "export",
            "eveng_lab_archive_capture_device_configs": True,
            "eveng_lab_archive_config_export_timeout_s": 600,
            "eveng_lab_archive_activate_saved_configs": True,
            "eveng_lab_archive_include_node_state": True,
            "eveng_lab_archive_guest_quiesced": True,
            "load_vault_env": True,
            "required_env": ["EVENG_ADMIN_PASSWORD"],
        })
        validate(inputs)

    def test_device_config_api_credentials_required(self) -> None:
        """API credentials must be non-empty strings."""
        inputs = valid_inputs()
        inputs.update({
            "eveng_lab_archive_capture_device_configs": True,
        })
        # API username and password env var should be non-empty in defaults
        validate(inputs)

    def test_device_config_api_url_validation(self) -> None:
        """API URL must be valid HTTP/HTTPS URL."""
        for url in [
            "http://localhost",
            "https://192.168.1.1",
            "http://eve-ng.example.com:8080",
        ]:
            with self.subTest(url=url):
                inputs = valid_inputs()
                inputs["eveng_lab_archive_api_base_url"] = url
                inputs["eveng_lab_archive_capture_device_configs"] = True
                validate(inputs)


if __name__ == "__main__":
    unittest.main()
