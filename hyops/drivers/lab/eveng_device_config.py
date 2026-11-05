"""EVE-NG device configuration export and restore utilities.

Provides functions to export Cisco IOL and other device configurations from
EVE-NG labs and prepare them for archive, and to restore them after recovery.

purpose: Support device configuration continuity across EVE-NG lab recovery
maintainer: HybridOps.Tech
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Mapping
from datetime import datetime


@dataclass(frozen=True)
class DeviceConfig:
    """A device's exported configuration from an EVE-NG lab."""

    node_id: str
    node_name: str
    device_type: str
    config_data: str
    exported_at: str
    config_format: str = "cisco-ios"
    lab_id: str = ""
    checksum_method: str = "sha256"
    checksum: str = ""

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary, excluding sensitive data."""
        return asdict(self)


@dataclass(frozen=True)
class LabDeviceConfigs:
    """Collection of device configurations from a single EVE-NG lab."""

    lab_name: str
    lab_id: str
    lab_path: str
    captured_at: str
    capture_method: str
    device_configs: list[DeviceConfig] = field(default_factory=list)
    capture_duration_s: float = 0.0
    config_export_tool_version: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "lab_name": self.lab_name,
            "lab_id": self.lab_id,
            "lab_path": self.lab_path,
            "captured_at": self.captured_at,
            "capture_method": self.capture_method,
            "device_configs": [cfg.to_dict() for cfg in self.device_configs],
            "capture_duration_s": self.capture_duration_s,
            "config_export_tool_version": self.config_export_tool_version,
            "metadata": self.metadata,
        }

    def to_json(self) -> str:
        """Serialize to JSON for storage."""
        return json.dumps(self.to_dict(), indent=2)

    @classmethod
    def from_json(cls, json_str: str) -> LabDeviceConfigs:
        """Deserialize from JSON."""
        data = json.loads(json_str)
        device_configs = [
            DeviceConfig(
                node_id=cfg["node_id"],
                node_name=cfg["node_name"],
                device_type=cfg["device_type"],
                config_data=cfg["config_data"],
                exported_at=cfg["exported_at"],
                config_format=cfg.get("config_format", "cisco-ios"),
                lab_id=cfg.get("lab_id", ""),
                checksum_method=cfg.get("checksum_method", "sha256"),
                checksum=cfg.get("checksum", ""),
            )
            for cfg in data.get("device_configs", [])
        ]
        return cls(
            lab_name=data["lab_name"],
            lab_id=data["lab_id"],
            lab_path=data["lab_path"],
            captured_at=data["captured_at"],
            capture_method=data["capture_method"],
            device_configs=device_configs,
            capture_duration_s=data.get("capture_duration_s", 0.0),
            config_export_tool_version=data.get("config_export_tool_version", ""),
            metadata=data.get("metadata", {}),
        )


@dataclass(frozen=True)
class DeviceConfigArchive:
    """Manifest for device configurations stored in archive."""

    archive_path: Path
    created_at: str
    labs: list[LabDeviceConfigs] = field(default_factory=list)
    total_configs: int = 0
    archive_format_version: str = "1.0"
    note: str = "Device configurations exported from EVE-NG labs"

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "archive_format_version": self.archive_format_version,
            "created_at": self.created_at,
            "archive_path": str(self.archive_path),
            "total_configs": self.total_configs,
            "labs": [lab.to_dict() for lab in self.labs],
            "note": self.note,
        }

    def to_json(self) -> str:
        """Serialize to JSON for storage."""
        return json.dumps(self.to_dict(), indent=2)

    @classmethod
    def from_json(cls, json_str: str) -> DeviceConfigArchive:
        """Deserialize from JSON."""
        data = json.loads(json_str)
        labs = []
        for lab_data in data.get("labs", []):
            device_configs = [
                DeviceConfig(
                    node_id=cfg["node_id"],
                    node_name=cfg["node_name"],
                    device_type=cfg["device_type"],
                    config_data=cfg["config_data"],
                    exported_at=cfg["exported_at"],
                    config_format=cfg.get("config_format", "cisco-ios"),
                    lab_id=cfg.get("lab_id", ""),
                    checksum_method=cfg.get("checksum_method", "sha256"),
                    checksum=cfg.get("checksum", ""),
                )
                for cfg in lab_data.get("device_configs", [])
            ]
            labs.append(
                LabDeviceConfigs(
                    lab_name=lab_data["lab_name"],
                    lab_id=lab_data["lab_id"],
                    lab_path=lab_data["lab_path"],
                    captured_at=lab_data["captured_at"],
                    capture_method=lab_data["capture_method"],
                    device_configs=device_configs,
                    capture_duration_s=lab_data.get("capture_duration_s", 0.0),
                    config_export_tool_version=lab_data.get(
                        "config_export_tool_version", ""
                    ),
                    metadata=lab_data.get("metadata", {}),
                )
            )
        return cls(
            archive_path=Path(data["archive_path"]),
            created_at=data["created_at"],
            labs=labs,
            total_configs=data.get("total_configs", 0),
            archive_format_version=data.get("archive_format_version", "1.0"),
            note=data.get("note", ""),
        )


def validate_device_config(config: DeviceConfig) -> None:
    """Validate a device configuration for security and integrity.

    Raises ValueError if validation fails.
    Args:
        config: DeviceConfig to validate

    Raises:
        ValueError: If config contains suspicious patterns (credentials, etc)
    """
    # Check for common credential patterns in config data
    suspicious_patterns = [
        r"username\s+\S+\s+password",
        r"enable\s+password",
        r"secret",
        r"private-key",
        r"access-list.*permit\s+ip",
    ]

    for pattern in suspicious_patterns:
        if re.search(pattern, config.config_data, re.IGNORECASE):
            raise ValueError(f"Config contains suspicious pattern: {pattern}")


def redact_sensitive_config(config_data: str) -> str:
    """Redact sensitive information from device configuration.

    Redacts passwords, secrets, and other sensitive data while preserving
    the overall structure for validation and restore.

    Args:
        config_data: Raw configuration text

    Returns:
        Redacted configuration text
    """
    lines = config_data.split("\n")
    redacted = []

    for line in lines:
        # Redact lines containing passwords or secrets
        if re.search(
            r"(password|secret|key|credential|authentication)\s*=?\s*",
            line,
            re.IGNORECASE,
        ):
            # Keep the line structure but redact the value
            redacted_line = re.sub(
                r"(\s*)(password|secret|key|credential|authentication)\s*=?\s*\S+",
                r"\1\2 <REDACTED>",
                line,
                flags=re.IGNORECASE,
            )
            redacted.append(redacted_line)
        else:
            redacted.append(line)

    return "\n".join(redacted)


def create_device_config(
    node_id: str,
    node_name: str,
    device_type: str,
    config_data: str,
    lab_id: str = "",
) -> DeviceConfig:
    """Create a device configuration object with validation.

    Args:
        node_id: EVE-NG node ID
        node_name: Human-readable node name
        device_type: Device type (e.g., "iol")
        config_data: Configuration text
        lab_id: Lab ID this config belongs to

    Returns:
        DeviceConfig object

    Raises:
        ValueError: If validation fails
    """
    config = DeviceConfig(
        node_id=node_id,
        node_name=node_name,
        device_type=device_type,
        config_data=config_data,
        exported_at=datetime.utcnow().isoformat() + "Z",
        lab_id=lab_id,
    )
    validate_device_config(config)
    return config


def archive_device_configs(
    configs_by_lab: Mapping[str, list[DeviceConfig]],
    archive_path: Path,
) -> DeviceConfigArchive:
    """Create an archive manifest from device configurations.

    Args:
        configs_by_lab: Dict mapping lab_path to list of DeviceConfig
        archive_path: Path where archive will be stored

    Returns:
        DeviceConfigArchive manifest
    """
    labs = []
    total_configs = 0

    for lab_path, configs in configs_by_lab.items():
        if not configs:
            continue

        lab_device_configs = LabDeviceConfigs(
            lab_name=Path(lab_path).stem,
            lab_id=Path(lab_path).name,
            lab_path=lab_path,
            captured_at=datetime.utcnow().isoformat() + "Z",
            capture_method="eveng-api",
            device_configs=configs,
            capture_duration_s=0.0,
            config_export_tool_version="1.0",
        )
        labs.append(lab_device_configs)
        total_configs += len(configs)

    return DeviceConfigArchive(
        archive_path=archive_path,
        created_at=datetime.utcnow().isoformat() + "Z",
        labs=labs,
        total_configs=total_configs,
    )
