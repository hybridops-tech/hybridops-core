"""
purpose: Validate inputs for platform/linux/eve-ng-healthcheck module.
maintainer: HybridOps.Tech
"""

from __future__ import annotations

from typing import Any

from hyops.validators.common import (
    normalize_lifecycle_command,
    normalize_required_env,
    require_bool,
    require_mapping,
    require_non_empty_str,
    require_str_list,
)
from hyops.validators.platform.linux._eve_ng_common import (
    require_secret_seeding,
    validate_target_access,
)


def validate(inputs: dict[str, Any]) -> None:
    data = require_mapping(inputs, "inputs")
    lifecycle_command = normalize_lifecycle_command(data)
    is_destroy = lifecycle_command == "destroy"

    required_env = normalize_required_env(data.get("required_env"), "inputs.required_env")
    if data.get("required_env_destroy") is not None:
        require_str_list(data.get("required_env_destroy"), "inputs.required_env_destroy")
    admin_env = require_non_empty_str(data.get("eveng_admin_password_env"), "inputs.eveng_admin_password_env")
    if data.get("load_vault_env") is not None:
        require_bool(data.get("load_vault_env"), "inputs.load_vault_env")
    load_vault_env = bool(data.get("load_vault_env"))
    if not is_destroy and bool(data.get("health_check_api")):
        require_secret_seeding(
            load_vault_env=load_vault_env,
            required_env=required_env,
            env_keys=[admin_env],
            module_ref="platform/linux/eve-ng-healthcheck",
        )

    context = validate_target_access(
        data,
        module_ref="platform/linux/eve-ng-healthcheck",
        require_ubuntu=True,
        require_eveng=True,
    )
    is_destroy = bool(context["is_destroy"])

    require_non_empty_str(data.get("eveng_healthcheck_role_fqcn"), "inputs.eveng_healthcheck_role_fqcn")
    level = require_non_empty_str(data.get("health_check_level"), "inputs.health_check_level").lower()
    if level not in {"basic", "images", "full"}:
        raise ValueError("inputs.health_check_level must be one of: basic, images, full")
    report_format = require_non_empty_str(data.get("health_check_report_format"), "inputs.health_check_report_format").lower()
    if report_format not in {"summary", "detailed", "json"}:
        raise ValueError("inputs.health_check_report_format must be one of: summary, detailed, json")

    for field in (
        "health_check_fail_on_warning",
        "health_check_save_output",
        "health_check_services",
        "health_check_database",
        "health_check_api",
        "health_check_kvm",
        "health_check_images",
        "health_check_labs",
    ):
        require_bool(data.get(field), f"inputs.{field}")

    require_non_empty_str(data.get("health_check_output_dir"), "inputs.health_check_output_dir")
    require_non_empty_str(data.get("health_check_reports_dir"), "inputs.health_check_reports_dir")
