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
_IMAGE_BUILD_VERSION_RE = re.compile(r"^[0-9][0-9A-Za-z._-]{0,63}$")
_LINUX_USER_RE = re.compile(r"^[a-z_][a-z0-9_-]{0,31}$")


def _validate_local_image_archives(value: Any) -> set[str]:
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
    return image_refs


def _validate_local_image_builds(value: Any, archive_refs: set[str]) -> None:
    if not isinstance(value, list):
        raise ValueError("inputs.containerlab_lab_local_image_builds must be a list")

    image_refs: set[str] = set()
    for index, raw in enumerate(value, start=1):
        label = f"inputs.containerlab_lab_local_image_builds[{index}]"
        item = require_mapping(raw, label)
        kind = require_non_empty_str(item.get("kind"), f"{label}.kind")
        source = require_non_empty_str(item.get("source"), f"{label}.source")
        version = require_non_empty_str(item.get("version"), f"{label}.version")
        image_type = item.get("type", "l3")
        source_format = item.get("format", "binary")

        if kind != "cisco_iol":
            raise ValueError(f"{label}.kind must be cisco_iol")
        if not source.startswith("/"):
            raise ValueError(f"{label}.source must be an absolute controller path")
        if not _IMAGE_BUILD_VERSION_RE.fullmatch(version):
            raise ValueError(f"{label}.version is not a valid image version")
        if image_type not in {"l3", "l2"}:
            raise ValueError(f"{label}.type must be l3 or l2")
        if source_format not in {"binary", "oci_archive"}:
            raise ValueError(f"{label}.format must be binary or oci_archive")
        if source_format == "oci_archive" and not re.fullmatch(
            r"[0-9]+(?:\.[0-9]+)+", version
        ):
            raise ValueError(
                f"{label}.version must be dotted numeric for an OCI archive"
            )

        authorised_use = require_bool(
            item.get("authorised_use"),
            f"{label}.authorised_use",
        )
        if not authorised_use:
            raise ValueError(f"{label}.authorised_use must be true")

        digest = item.get("sha256")
        if digest is not None:
            digest = require_non_empty_str(digest, f"{label}.sha256")
            if not _SHA256_RE.fullmatch(digest):
                raise ValueError(f"{label}.sha256 must contain 64 lowercase hex characters")

        tag = f"L2-{version}" if image_type == "l2" else version
        image = f"vrnetlab/cisco_iol:{tag}"
        if image in image_refs:
            raise ValueError(f"{label} duplicates an earlier expected image")
        if image in archive_refs:
            raise ValueError(f"{label} duplicates a local image archive")
        image_refs.add(image)


def validate(inputs: dict[str, Any]) -> None:
    data = require_mapping(inputs, "inputs")
    validate_target_access(
        data,
        module_ref="platform/linux/containerlab-lab",
        require_ubuntu=True,
        require_eveng=False,
        allow_ubuntu_24=True,
    )
    require_non_empty_str(
        data.get("containerlab_lab_role_fqcn"),
        "inputs.containerlab_lab_role_fqcn",
    )
    require_non_empty_str(
        data.get("containerlab_lab_recovery_role_fqcn"),
        "inputs.containerlab_lab_recovery_role_fqcn",
    )
    remote_owner = require_non_empty_str(
        data.get("containerlab_lab_remote_owner"),
        "inputs.containerlab_lab_remote_owner",
    )
    if not _LINUX_USER_RE.fullmatch(remote_owner):
        raise ValueError("inputs.containerlab_lab_remote_owner is invalid")
    require_non_empty_str(
        data.get("containerlab_lab_image_cache_dir"),
        "inputs.containerlab_lab_image_cache_dir",
    )
    require_bool(
        data.get("containerlab_lab_pull_missing_images"),
        "inputs.containerlab_lab_pull_missing_images",
    )
    require_bool(
        data.get("containerlab_lab_destroy_all"),
        "inputs.containerlab_lab_destroy_all",
    )
    archive_refs = _validate_local_image_archives(
        data.get("containerlab_lab_local_image_archives")
    )
    local_image_dir = data.get("containerlab_lab_local_image_dir")
    if not isinstance(local_image_dir, str):
        raise ValueError("inputs.containerlab_lab_local_image_dir must be a string")
    local_image_dir = local_image_dir.strip()
    if local_image_dir and not local_image_dir.startswith("/"):
        raise ValueError(
            "inputs.containerlab_lab_local_image_dir must be an absolute controller path"
        )
    local_image_dir_authorised_use = require_bool(
        data.get("containerlab_lab_local_image_dir_authorised_use"),
        "inputs.containerlab_lab_local_image_dir_authorised_use",
    )
    if local_image_dir and not local_image_dir_authorised_use:
        raise ValueError(
            "inputs.containerlab_lab_local_image_dir_authorised_use must be true "
            "when image-directory discovery is enabled"
        )
    local_image_builds = data.get("containerlab_lab_local_image_builds")
    if local_image_dir and local_image_builds:
        raise ValueError(
            "inputs.containerlab_lab_local_image_dir cannot be combined with "
            "containerlab_lab_local_image_builds"
        )
    _validate_local_image_builds(
        local_image_builds,
        archive_refs,
    )
    image_build_root = require_non_empty_str(
        data.get("containerlab_lab_image_build_root"),
        "inputs.containerlab_lab_image_build_root",
    )
    if not image_build_root.startswith("/"):
        raise ValueError("inputs.containerlab_lab_image_build_root must be an absolute path")
    require_non_empty_str(
        data.get("containerlab_lab_vrnetlab_repository"),
        "inputs.containerlab_lab_vrnetlab_repository",
    )
    revision = require_non_empty_str(
        data.get("containerlab_lab_vrnetlab_revision"),
        "inputs.containerlab_lab_vrnetlab_revision",
    )
    if not re.fullmatch(r"[0-9a-f]{40}", revision):
        raise ValueError(
            "inputs.containerlab_lab_vrnetlab_revision must be a full lowercase commit SHA"
        )
