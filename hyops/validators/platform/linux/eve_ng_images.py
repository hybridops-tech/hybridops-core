"""
purpose: Validate inputs for platform/linux/eve-ng-images module.
maintainer: HybridOps.Tech
"""

from __future__ import annotations

from typing import Any

from hyops.validators.common import (
    normalize_required_env,
    require_bool,
    require_mapping,
    require_non_empty_str,
    require_str_list,
)
from hyops.validators.platform.linux._eve_ng_common import (
    validate_target_access,
)


def _validate_image_list(value: Any) -> None:
    if not isinstance(value, list) or not value:
        raise ValueError("inputs.eveng_images_list must be a non-empty list when inputs.eveng_images_source=url")
    for idx, item in enumerate(value, start=1):
        if not isinstance(item, dict):
            raise ValueError(f"inputs.eveng_images_list[{idx}] must be a mapping")
        require_non_empty_str(item.get("url"), f"inputs.eveng_images_list[{idx}].url")
        if item.get("name") is not None and str(item.get("name") or "").strip():
            require_non_empty_str(item.get("name"), f"inputs.eveng_images_list[{idx}].name")
        image_type = require_non_empty_str(item.get("type"), f"inputs.eveng_images_list[{idx}].type").lower()
        if image_type not in {"qemu", "iol", "dynamips"}:
            raise ValueError(f"inputs.eveng_images_list[{idx}].type must be one of: qemu, iol, dynamips")


def _validate_destroy_paths(value: Any) -> None:
    if value is None:
        return
    paths = require_str_list(value, "inputs.eveng_images_destroy_paths")
    for idx, path in enumerate(paths, start=1):
        if not path.startswith("/opt/unetlab/addons/"):
            raise ValueError(
                f"inputs.eveng_images_destroy_paths[{idx}] must stay under /opt/unetlab/addons/"
            )


def validate(inputs: dict[str, Any]) -> None:
    data = require_mapping(inputs, "inputs")
    validate_target_access(
        data,
        module_ref="platform/linux/eve-ng-images",
        require_ubuntu=True,
        require_eveng=True,
    )

    require_non_empty_str(data.get("eveng_images_role_fqcn"), "inputs.eveng_images_role_fqcn")
    source = require_non_empty_str(data.get("eveng_images_source"), "inputs.eveng_images_source").lower()
    if source not in {"url", "local", "remote"}:
        raise ValueError("inputs.eveng_images_source must be one of: url, local, remote")
    require_bool(data.get("eveng_images_download"), "inputs.eveng_images_download")
    require_bool(data.get("eveng_images_install"), "inputs.eveng_images_install")
    if not bool(data.get("eveng_images_download")) and not bool(data.get("eveng_images_install")):
        raise ValueError("inputs.eveng_images_download and inputs.eveng_images_install cannot both be false")
    require_non_empty_str(data.get("eveng_images_cache_dir"), "inputs.eveng_images_cache_dir")
    require_bool(data.get("eveng_images_keep_cache"), "inputs.eveng_images_keep_cache")
    raw_layout = require_non_empty_str(data.get("eveng_images_raw_qemu_layout"), "inputs.eveng_images_raw_qemu_layout").lower()
    if raw_layout not in {"foldered", "generic"}:
        raise ValueError("inputs.eveng_images_raw_qemu_layout must be one of: foldered, generic")
    require_non_empty_str(data.get("eveng_images_raw_qemu_disk_name"), "inputs.eveng_images_raw_qemu_disk_name")
    require_bool(data.get("eveng_images_fail_on_corrupt"), "inputs.eveng_images_fail_on_corrupt")
    require_bool(data.get("eveng_images_logging_enabled"), "inputs.eveng_images_logging_enabled")
    require_non_empty_str(data.get("eveng_images_log_dir_controller"), "inputs.eveng_images_log_dir_controller")
    require_non_empty_str(data.get("eveng_images_download_log"), "inputs.eveng_images_download_log")
    require_bool(data.get("eveng_images_generate_report"), "inputs.eveng_images_generate_report")
    require_non_empty_str(data.get("eveng_images_report_dir_controller"), "inputs.eveng_images_report_dir_controller")
    require_bool(data.get("eveng_images_debug"), "inputs.eveng_images_debug")
    _validate_destroy_paths(data.get("eveng_images_destroy_paths"))

    if data.get("required_env_destroy") is not None:
        require_str_list(data.get("required_env_destroy"), "inputs.required_env_destroy")
    normalize_required_env(data.get("required_env"), "inputs.required_env")

    if source == "url":
        _validate_image_list(data.get("eveng_images_list"))
    elif source == "local":
        require_non_empty_str(data.get("eveng_images_local_path"), "inputs.eveng_images_local_path")
    else:
        require_non_empty_str(data.get("eveng_images_remote_host"), "inputs.eveng_images_remote_host")
        require_non_empty_str(data.get("eveng_images_remote_path"), "inputs.eveng_images_remote_path")
