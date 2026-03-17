"""
purpose: Validate inputs for platform/linux/eve-ng-labs module.
Architecture Decision: ADR-N/A (linux eve-ng labs validator)
maintainer: HybridOps.Tech
"""

from __future__ import annotations

from typing import Any

from hyops.validators.platform.linux._eve_ng_common import (
    normalize_required_env,
    require_mapping,
    require_non_empty_str,
    require_str_list,
    validate_target_access,
)


def _validate_relative_paths(value: Any, field: str) -> list[str]:
    paths = require_str_list(value, field)
    for idx, path in enumerate(paths, start=1):
        if path.startswith("/") or ".." in path.split("/"):
            raise ValueError(f"{field}[{idx}] must be a relative path under /opt/unetlab/labs")
    return paths


def validate(inputs: dict[str, Any]) -> None:
    data = require_mapping(inputs, "inputs")
    validate_target_access(
        data,
        module_ref="platform/linux/eve-ng-labs",
        require_ubuntu=True,
        require_eveng=True,
    )

    require_non_empty_str(data.get("eveng_labs_role_fqcn"), "inputs.eveng_labs_role_fqcn")
    source = require_non_empty_str(data.get("eveng_labs_source"), "inputs.eveng_labs_source").lower()
    if source not in {"local", "git", "remote"}:
        raise ValueError("inputs.eveng_labs_source must be one of: local, git, remote")
    require_non_empty_str(data.get("eveng_labs_staging_dir"), "inputs.eveng_labs_staging_dir")

    if data.get("eveng_lab_folders") is not None and list(data.get("eveng_lab_folders") or []):
        _validate_relative_paths(data.get("eveng_lab_folders"), "inputs.eveng_lab_folders")
    if data.get("eveng_exclude_patterns") is not None:
        require_str_list(data.get("eveng_exclude_patterns"), "inputs.eveng_exclude_patterns")
    if data.get("eveng_labs_sync_exclude_patterns") is not None:
        require_str_list(data.get("eveng_labs_sync_exclude_patterns"), "inputs.eveng_labs_sync_exclude_patterns")

    if source == "local":
        require_non_empty_str(data.get("eveng_labs_local_path"), "inputs.eveng_labs_local_path")
    elif source == "git":
        require_non_empty_str(data.get("eveng_labs_git_repo"), "inputs.eveng_labs_git_repo")
        require_non_empty_str(data.get("eveng_labs_git_branch"), "inputs.eveng_labs_git_branch")
    else:
        require_non_empty_str(data.get("eveng_labs_remote_host"), "inputs.eveng_labs_remote_host")
        require_non_empty_str(data.get("eveng_labs_remote_path"), "inputs.eveng_labs_remote_path")

    if data.get("required_env_destroy") is not None:
        require_str_list(data.get("required_env_destroy"), "inputs.required_env_destroy")
    normalize_required_env(data.get("required_env"))
