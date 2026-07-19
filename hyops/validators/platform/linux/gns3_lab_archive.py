"""
purpose: Validate inputs for platform/linux/gns3-lab-archive module.
maintainer: HybridOps.Tech
"""

from __future__ import annotations

from pathlib import PurePath
import re
from typing import Any

from hyops.validators.common import (
    normalize_required_env,
    require_mapping,
    require_non_empty_str,
    require_port,
    require_str_list,
)
from hyops.validators.platform.linux._eve_ng_common import validate_target_access


_SHA256_RE = re.compile(r"^[0-9a-fA-F]{64}$")


def validate(inputs: dict[str, Any]) -> None:
    data = require_mapping(inputs, "inputs")
    validate_target_access(
        data,
        module_ref="platform/linux/gns3-lab-archive",
        require_ubuntu=True,
        require_eveng=False,
    )
    require_non_empty_str(
        data.get("gns3_lab_archive_role_fqcn"),
        "inputs.gns3_lab_archive_role_fqcn",
    )
    action = require_non_empty_str(
        data.get("gns3_lab_archive_action"),
        "inputs.gns3_lab_archive_action",
    ).lower()
    if action not in {"export", "restore"}:
        raise ValueError("inputs.gns3_lab_archive_action must be export or restore")

    for field in (
        "gns3_lab_archive_data_root",
        "gns3_lab_archive_remote_dir",
    ):
        value = require_non_empty_str(data.get(field), f"inputs.{field}")
        if not value.startswith("/"):
            raise ValueError(f"inputs.{field} must be an absolute path")

    if action == "export":
        archive_name = require_non_empty_str(
            data.get("gns3_lab_archive_name"),
            "inputs.gns3_lab_archive_name",
        )
        if archive_name != PurePath(archive_name).name:
            raise ValueError("inputs.gns3_lab_archive_name must be a safe filename")
    else:
        archive_path = require_non_empty_str(
            data.get("gns3_lab_archive_path"),
            "inputs.gns3_lab_archive_path",
        )
        if not archive_path.startswith("/"):
            raise ValueError("inputs.gns3_lab_archive_path must be an absolute path")
        checksum = require_non_empty_str(
            data.get("gns3_lab_archive_expected_sha256"),
            "inputs.gns3_lab_archive_expected_sha256",
        )
        if not _SHA256_RE.fullmatch(checksum):
            raise ValueError(
                "inputs.gns3_lab_archive_expected_sha256 must contain "
                "64 hexadecimal characters"
            )

    for field in (
        "gns3_lab_archive_overwrite",
        "gns3_lab_archive_include_images",
        "gns3_lab_archive_manage_service",
    ):
        if not isinstance(data.get(field), bool):
            raise ValueError(f"inputs.{field} must be a boolean")

    require_port(data.get("gns3_lab_archive_port"), "inputs.gns3_lab_archive_port")
    require_non_empty_str(
        data.get("gns3_lab_archive_username"),
        "inputs.gns3_lab_archive_username",
    )
    require_non_empty_str(
        data.get("gns3_lab_archive_password_env"),
        "inputs.gns3_lab_archive_password_env",
    )
    if data.get("required_env_destroy") is not None:
        require_str_list(data.get("required_env_destroy"), "inputs.required_env_destroy")
    normalize_required_env(data.get("required_env"), "inputs.required_env")
