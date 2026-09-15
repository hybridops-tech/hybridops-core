"""
purpose: Validate inputs for platform/linux/containerlab-lab module.
maintainer: HybridOps.Tech
"""

from __future__ import annotations

import re
from typing import Any

from hyops.validators.common import (
    require_bool,
    require_mapping,
    require_non_empty_str,
)
from hyops.validators.platform.linux._eve_ng_common import validate_target_access


_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


def _validate_local_image_archives(value: Any) -> None:
    if not isinstance(value, list):
        raise ValueError("inputs.containerlab_lab_local_image_archives must be a list")

    image_refs: set[str] = set()
    for index, raw in enumerate(value, start=1):
        label = f"inputs.containerlab_lab_local_image_archives[{index}]"
        item = require_mapping(raw, label)
        path = require_non_empty_str(item.get("path"), f"{label}.path")
        image = require_non_empty_str(item.get("image"), f"{label}.image")
        if not path.startswith("/"):
            raise ValueError(f"{label}.path must be an absolute controller path")

        digest = item.get("sha256")
        if digest is not None:
            digest = require_non_empty_str(digest, f"{label}.sha256")
            if not _SHA256_RE.fullmatch(digest):
                raise ValueError(f"{label}.sha256 must contain 64 lowercase hex characters")

        if image in image_refs:
            raise ValueError(f"{label}.image duplicates an earlier expected image")
        image_refs.add(image)


def validate(inputs: dict[str, Any]) -> None:
    data = require_mapping(inputs, "inputs")
    validate_target_access(
        data,
        module_ref="platform/linux/containerlab-lab",
        require_ubuntu=True,
        require_eveng=False,
    )
    require_non_empty_str(
        data.get("containerlab_lab_role_fqcn"),
        "inputs.containerlab_lab_role_fqcn",
    )
    require_non_empty_str(
        data.get("containerlab_lab_recovery_role_fqcn"),
        "inputs.containerlab_lab_recovery_role_fqcn",
    )
    require_non_empty_str(
        data.get("containerlab_lab_image_cache_dir"),
        "inputs.containerlab_lab_image_cache_dir",
    )
    require_bool(
        data.get("containerlab_lab_pull_missing_images"),
        "inputs.containerlab_lab_pull_missing_images",
    )
    _validate_local_image_archives(data.get("containerlab_lab_local_image_archives"))
