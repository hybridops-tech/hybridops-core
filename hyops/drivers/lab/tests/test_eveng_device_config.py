"""Tests for EVE-NG device configuration export and restore.

purpose: Verify device configuration capture, validation, and archiving
maintainer: HybridOps.Tech
"""

from __future__ import annotations

import json
import unittest
from datetime import datetime
from pathlib import Path

from hyops.drivers.lab.eveng_device_config import (
    DeviceConfig,
    LabDeviceConfigs,
    DeviceConfigArchive,
    validate_device_config,
    redact_sensitive_config,
    create_device_config,
    archive_device_configs,
)


class TestDeviceConfig(unittest.TestCase):
    """Test DeviceConfig dataclass and operations."""

    def test_create_device_config_with_valid_data(self) -> None:
        """Create device config from valid IOL configuration."""
        config_text = """
interface Ethernet0/0
 ip address 10.0.0.1 255.255.255.0
 no shutdown
!
router ospf 1
 network 10.0.0.0 0.0.0.255 area 0
!
"""
        config = DeviceConfig(
            node_id="node1",
            node_name="Router1",
            device_type="iol",
            config_data=config_text,
            exported_at=datetime.utcnow().isoformat() + "Z",
        )

        self.assertEqual(config.node_id, "node1")
        self.assertEqual(config.node_name, "Router1")
        self.assertEqual(config.device_type, "iol")
        self.assertIn("Ethernet0/0", config.config_data)

    def test_device_config_to_dict(self) -> None:
        """Convert device config to dictionary."""
        config = DeviceConfig(
            node_id="node1",
            node_name="Router1",
            device_type="iol",
            config_data="config text",
            exported_at="2026-11-06T10:00:00Z",
        )

        result = config.to_dict()

        self.assertIsInstance(result, dict)
        self.assertEqual(result["node_id"], "node1")
        self.assertEqual(result["node_name"], "Router1")
        self.assertEqual(result["device_type"], "iol")

    def test_device_config_serialization(self) -> None:
        """Serialize and deserialize device config."""
        config = DeviceConfig(
            node_id="node1",
            node_name="Router1",
            device_type="iol",
            config_data="config data",
            exported_at="2026-11-06T10:00:00Z",
            lab_id="lab123",
        )

        json_str = json.dumps(config.to_dict())
        data = json.loads(json_str)

        self.assertEqual(data["node_id"], "node1")
        self.assertEqual(data["lab_id"], "lab123")


class TestLabDeviceConfigs(unittest.TestCase):
    """Test LabDeviceConfigs collection."""

    def test_create_lab_device_configs(self) -> None:
        """Create collection of device configs from a lab."""
        configs = [
            DeviceConfig(
                node_id="node1",
                node_name="Router1",
                device_type="iol",
                config_data="config1",
                exported_at="2026-11-06T10:00:00Z",
            ),
            DeviceConfig(
                node_id="node2",
                node_name="Router2",
                device_type="iol",
                config_data="config2",
                exported_at="2026-11-06T10:00:00Z",
            ),
        ]

        lab_configs = LabDeviceConfigs(
            lab_name="enterprise-wan",
            lab_id="lab123",
            lab_path="/opt/unetlab/labs/enterprise-wan.unl",
            captured_at="2026-11-06T10:00:00Z",
            capture_method="eveng-api",
            device_configs=configs,
        )

        self.assertEqual(lab_configs.lab_name, "enterprise-wan")
        self.assertEqual(len(lab_configs.device_configs), 2)

    def test_lab_device_configs_serialization(self) -> None:
        """Serialize and deserialize lab device configs."""
        config = DeviceConfig(
            node_id="node1",
            node_name="Router1",
            device_type="iol",
            config_data="config text",
            exported_at="2026-11-06T10:00:00Z",
        )

        lab_configs = LabDeviceConfigs(
            lab_name="test-lab",
            lab_id="lab123",
            lab_path="/path/to/lab.unl",
            captured_at="2026-11-06T10:00:00Z",
            capture_method="eveng-api",
            device_configs=[config],
        )

        json_str = lab_configs.to_json()
        restored = LabDeviceConfigs.from_json(json_str)

        self.assertEqual(restored.lab_name, "test-lab")
        self.assertEqual(len(restored.device_configs), 1)
        self.assertEqual(restored.device_configs[0].node_name, "Router1")


class TestDeviceConfigArchive(unittest.TestCase):
    """Test device config archive manifest."""

    def test_create_device_config_archive(self) -> None:
        """Create archive manifest from lab configs."""
        config = DeviceConfig(
            node_id="node1",
            node_name="Router1",
            device_type="iol",
            config_data="config",
            exported_at="2026-11-06T10:00:00Z",
        )

        lab_configs = LabDeviceConfigs(
            lab_name="test-lab",
            lab_id="lab123",
            lab_path="/path/to/lab.unl",
            captured_at="2026-11-06T10:00:00Z",
            capture_method="eveng-api",
            device_configs=[config],
        )

        archive = DeviceConfigArchive(
            archive_path=Path("/tmp/device-configs.json"),
            created_at="2026-11-06T10:00:00Z",
            labs=[lab_configs],
            total_configs=1,
        )

        self.assertEqual(archive.total_configs, 1)
        self.assertEqual(len(archive.labs), 1)
        self.assertEqual(archive.labs[0].lab_name, "test-lab")

    def test_archive_serialization(self) -> None:
        """Serialize and deserialize archive manifest."""
        config = DeviceConfig(
            node_id="node1",
            node_name="Router1",
            device_type="iol",
            config_data="config",
            exported_at="2026-11-06T10:00:00Z",
        )

        lab_configs = LabDeviceConfigs(
            lab_name="test-lab",
            lab_id="lab123",
            lab_path="/path/to/lab.unl",
            captured_at="2026-11-06T10:00:00Z",
            capture_method="eveng-api",
            device_configs=[config],
        )

        archive = DeviceConfigArchive(
            archive_path=Path("/tmp/device-configs.json"),
            created_at="2026-11-06T10:00:00Z",
            labs=[lab_configs],
            total_configs=1,
        )

        json_str = archive.to_json()
        restored = DeviceConfigArchive.from_json(json_str)

        self.assertEqual(restored.total_configs, 1)
        self.assertEqual(len(restored.labs), 1)


class TestConfigValidation(unittest.TestCase):
    """Test configuration validation and sanitization."""

    def test_validate_clean_config(self) -> None:
        """Valid configs without credentials pass validation."""
        config = DeviceConfig(
            node_id="node1",
            node_name="Router1",
            device_type="iol",
            config_data="interface Ethernet0/0\n ip address 10.0.0.1 255.255.255.0",
            exported_at="2026-11-06T10:00:00Z",
        )

        # Should not raise
        validate_device_config(config)

    def test_redact_sensitive_config(self) -> None:
        """Redact passwords and secrets from config."""
        config_with_secrets = """
username admin privilege 15 password cisco123
enable password secret123
line vty 0 4
 password telnet123
!
"""
        redacted = redact_sensitive_config(config_with_secrets)

        self.assertNotIn("cisco123", redacted)
        self.assertNotIn("secret123", redacted)
        self.assertNotIn("telnet123", redacted)
        self.assertIn("<REDACTED>", redacted)
        self.assertIn("username admin", redacted)

    def test_redaction_preserves_structure(self) -> None:
        """Redaction preserves config structure for validation."""
        config = "line vty 0 4\n password mypassword123\n login"
        redacted = redact_sensitive_config(config)

        self.assertIn("line vty 0 4", redacted)
        self.assertIn("login", redacted)
        self.assertIn("password", redacted)


class TestCreateDeviceConfig(unittest.TestCase):
    """Test device config factory function."""

    def test_create_device_config_with_validation(self) -> None:
        """Create and validate device config."""
        config_text = """
interface Ethernet0/0
 ip address 192.168.1.1 255.255.255.0
!
"""
        config = create_device_config(
            node_id="node1",
            node_name="Router1",
            device_type="iol",
            config_data=config_text,
            lab_id="lab123",
        )

        self.assertEqual(config.node_id, "node1")
        self.assertEqual(config.lab_id, "lab123")
        self.assertIsNotNone(config.exported_at)

    def test_create_config_factory_includes_timestamp(self) -> None:
        """Config factory adds export timestamp."""
        config = create_device_config(
            node_id="n1",
            node_name="R1",
            device_type="iol",
            config_data="interface e0/0",
        )

        self.assertTrue(config.exported_at.endswith("Z"))
        self.assertIn("T", config.exported_at)


class TestArchiveDeviceConfigs(unittest.TestCase):
    """Test archiving device configurations."""

    def test_archive_multiple_labs(self) -> None:
        """Archive configs from multiple labs."""
        config1 = DeviceConfig(
            node_id="n1",
            node_name="R1",
            device_type="iol",
            config_data="config1",
            exported_at="2026-11-06T10:00:00Z",
        )
        config2 = DeviceConfig(
            node_id="n2",
            node_name="R2",
            device_type="iol",
            config_data="config2",
            exported_at="2026-11-06T10:00:00Z",
        )

        configs_by_lab = {
            "/path/to/lab1.unl": [config1],
            "/path/to/lab2.unl": [config2],
        }

        archive = archive_device_configs(
            configs_by_lab, Path("/tmp/archive.json")
        )

        self.assertEqual(archive.total_configs, 2)
        self.assertEqual(len(archive.labs), 2)

    def test_archive_skips_empty_labs(self) -> None:
        """Archive function skips labs with no configs."""
        config = DeviceConfig(
            node_id="n1",
            node_name="R1",
            device_type="iol",
            config_data="config",
            exported_at="2026-11-06T10:00:00Z",
        )

        configs_by_lab = {
            "/path/to/lab1.unl": [config],
            "/path/to/lab2.unl": [],
        }

        archive = archive_device_configs(
            configs_by_lab, Path("/tmp/archive.json")
        )

        self.assertEqual(archive.total_configs, 1)
        self.assertEqual(len(archive.labs), 1)


if __name__ == "__main__":
    unittest.main()
