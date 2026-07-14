"""
purpose: Validate inputs for platform/linux/eve-ng-lab-archive module.
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
    require_str_list,
)
from hyops.validators.platform.linux._eve_ng_common import validate_target_access


_SHA256_RE = re.compile(r"^[0-9a-fA-F]{64}$")


def _relative_paths(value: Any, field: str) -> None:
    for index, path in enumerate(require_str_list(value, field), start=1):
        if path.startswith("/") or ".." in PurePath(path).parts:
            raise ValueError(f"{field}[{index}] must be a safe relative path")


def validate(inputs: dict[str, Any]) -> None:
    data = require_mapping(inputs, "inputs")
    validate_target_access(
        data,
        module_ref="platform/linux/eve-ng-lab-archive",
        require_ubuntu=True,
        require_eveng=True,
    )
    require_non_empty_str(
        data.get("eveng_lab_archive_role_fqcn"),
        "inputs.eveng_lab_archive_role_fqcn",
    )
    action = require_non_empty_str(
        data.get("eveng_lab_archive_action"),
        "inputs.eveng_lab_archive_action",
    ).lower()
    if action not in {"export", "restore"}:
        raise ValueError("inputs.eveng_lab_archive_action must be export or restore")

    require_non_empty_str(
        data.get("eveng_lab_archive_labs_root"),
        "inputs.eveng_lab_archive_labs_root",
    )
    _relative_paths(
        data.get("eveng_lab_archive_folders"),
        "inputs.eveng_lab_archive_folders",
    )
    require_non_empty_str(
        data.get("eveng_lab_archive_remote_dir"),
        "inputs.eveng_lab_archive_remote_dir",
    )
    if action == "export":
        archive_name = require_non_empty_str(
            data.get("eveng_lab_archive_name"),
            "inputs.eveng_lab_archive_name",
        )
        if archive_name != PurePath(archive_name).name:
            raise ValueError("inputs.eveng_lab_archive_name must be a safe filename")
    else:
        archive_path = require_non_empty_str(
            data.get("eveng_lab_archive_path"),
            "inputs.eveng_lab_archive_path",
        )
        if not archive_path.startswith("/"):
            raise ValueError("inputs.eveng_lab_archive_path must be an absolute path")
        checksum = require_non_empty_str(
            data.get("eveng_lab_archive_expected_sha256"),
            "inputs.eveng_lab_archive_expected_sha256",
        )
        if not _SHA256_RE.fullmatch(checksum):
            raise ValueError(
                "inputs.eveng_lab_archive_expected_sha256 must contain 64 hexadecimal characters"
            )
    if not isinstance(data.get("eveng_lab_archive_overwrite"), bool):
        raise ValueError("inputs.eveng_lab_archive_overwrite must be a boolean")
    if data.get("required_env_destroy") is not None:
        require_str_list(data.get("required_env_destroy"), "inputs.required_env_destroy")
    normalize_required_env(data.get("required_env"), "inputs.required_env")
