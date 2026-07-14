"""
purpose: Validate inputs for platform/linux/gns3-images module.
maintainer: HybridOps.Tech
"""

from __future__ import annotations

from pathlib import PurePath
import re
from typing import Any
from urllib.parse import urlparse

from hyops.validators.common import (
    normalize_required_env,
    require_mapping,
    require_non_empty_str,
    require_port,
    require_str_list,
)
from hyops.validators.platform.linux._eve_ng_common import validate_target_access


_SHA256_RE = re.compile(r"^sha256:[0-9a-fA-F]{64}$")


def _positive_int(value: Any, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ValueError(f"{label} must be an integer >= 1")
    return value


def _validate_template(value: Any, label: str) -> None:
    template = require_mapping(value, label)
    for key in ("ram", "cpus", "adapters"):
        if key in template:
            _positive_int(template[key], f"{label}.{key}")
    for key in (
        "adapter_type",
        "category",
        "console_type",
        "hda_disk_interface",
        "platform",
        "qemu_path",
        "symbol",
    ):
        if key in template:
            require_non_empty_str(template[key], f"{label}.{key}")
    if "linked_clone" in template and not isinstance(template["linked_clone"], bool):
        raise ValueError(f"{label}.linked_clone must be a boolean")


def _validate_images(value: Any) -> None:
    if not isinstance(value, list) or not value:
        raise ValueError("inputs.gns3_images_items must be a non-empty list")

    names: set[str] = set()
    filenames: set[str] = set()
    for index, raw in enumerate(value, start=1):
        label = f"inputs.gns3_images_items[{index}]"
        item = require_mapping(raw, label)
        name = require_non_empty_str(item.get("name"), f"{label}.name")
        url = require_non_empty_str(item.get("url"), f"{label}.url")
        filename = require_non_empty_str(item.get("filename"), f"{label}.filename")
        checksum = require_non_empty_str(item.get("checksum"), f"{label}.checksum")
        disk_type = require_non_empty_str(
            item.get("disk_type", "hda"), f"{label}.disk_type"
        ).lower()

        parsed = urlparse(url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError(f"{label}.url must be an HTTP or HTTPS URL")
        if filename != PurePath(filename).name or filename in {".", ".."}:
            raise ValueError(f"{label}.filename must be a safe basename")
        if not _SHA256_RE.fullmatch(checksum):
            raise ValueError(f"{label}.checksum must use sha256:<64 hex characters>")
        if disk_type not in {"hda", "cdrom"}:
            raise ValueError(f"{label}.disk_type must be hda or cdrom")
        if name in names:
            raise ValueError(f"{label}.name duplicates an earlier declaration")
        if filename in filenames:
            raise ValueError(f"{label}.filename duplicates an earlier declaration")
        names.add(name)
        filenames.add(filename)

        if item.get("timeout") is not None:
            _positive_int(item["timeout"], f"{label}.timeout")
        if item.get("template") is not None:
            _validate_template(item["template"], f"{label}.template")


def validate(inputs: dict[str, Any]) -> None:
    data = require_mapping(inputs, "inputs")
    validate_target_access(
        data,
        module_ref="platform/linux/gns3-images",
        require_ubuntu=True,
        require_eveng=False,
    )
    require_non_empty_str(data.get("gns3_images_role_fqcn"), "inputs.gns3_images_role_fqcn")
    require_port(data.get("gns3_images_port"), "inputs.gns3_images_port")
    require_non_empty_str(data.get("gns3_images_username"), "inputs.gns3_images_username")
    require_non_empty_str(
        data.get("gns3_images_password_env"), "inputs.gns3_images_password_env"
    )
    normalize_required_env(data.get("required_env"), "inputs.required_env")
    if data.get("required_env_destroy") is not None:
        require_str_list(data.get("required_env_destroy"), "inputs.required_env_destroy")
    _validate_images(data.get("gns3_images_items"))
