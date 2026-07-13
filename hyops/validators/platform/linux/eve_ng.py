"""
purpose: Validate inputs for platform/linux/eve-ng module.
maintainer: HybridOps.Tech
"""

from __future__ import annotations

import ipaddress
import re
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


def _validate_users(value: Any) -> None:
    if value is None:
        return
    if not isinstance(value, list):
        raise ValueError("inputs.eveng_users must be a list when set")
    for idx, raw_user in enumerate(value, start=1):
        if not isinstance(raw_user, dict):
            raise ValueError(f"inputs.eveng_users[{idx}] must be a mapping")
        require_non_empty_str(raw_user.get("username"), f"inputs.eveng_users[{idx}].username")
        require_non_empty_str(raw_user.get("name"), f"inputs.eveng_users[{idx}].name")
        require_non_empty_str(raw_user.get("email"), f"inputs.eveng_users[{idx}].email")
        require_non_empty_str(raw_user.get("password"), f"inputs.eveng_users[{idx}].password")
        role = require_non_empty_str(raw_user.get("role"), f"inputs.eveng_users[{idx}].role").lower()
        if role not in {"user", "admin"}:
            raise ValueError(f"inputs.eveng_users[{idx}].role must be one of: user, admin")


def validate(inputs: dict[str, Any]) -> None:
    data = require_mapping(inputs, "inputs")
    lifecycle_command = normalize_lifecycle_command(data)
    is_destroy = lifecycle_command == "destroy"

    required_env = normalize_required_env(data.get("required_env"), "inputs.required_env")
    if data.get("required_env_destroy") is not None:
        require_str_list(data.get("required_env_destroy"), "inputs.required_env_destroy")

    eveng_root_password_env = require_non_empty_str(data.get("eveng_root_password_env"), "inputs.eveng_root_password_env")
    eveng_admin_password_env = require_non_empty_str(
        data.get("eveng_admin_password_env"), "inputs.eveng_admin_password_env"
    )
    if data.get("load_vault_env") is not None:
        require_bool(data.get("load_vault_env"), "inputs.load_vault_env")
    load_vault_env = bool(data.get("load_vault_env"))
    if not is_destroy:
        require_secret_seeding(
            load_vault_env=load_vault_env,
            required_env=required_env,
            env_keys=[eveng_root_password_env, eveng_admin_password_env],
            module_ref="platform/linux/eve-ng",
        )

    context = validate_target_access(
        data,
        module_ref="platform/linux/eve-ng",
        require_ubuntu=True,
        require_eveng=False,
    )
    is_destroy = bool(context["is_destroy"])

    require_non_empty_str(data.get("eveng_role_fqcn"), "inputs.eveng_role_fqcn")
    profile = require_non_empty_str(data.get("eveng_resource_profile"), "inputs.eveng_resource_profile").lower()
    if profile not in {"minimal", "standard", "performance"}:
        raise ValueError("inputs.eveng_resource_profile must be one of: minimal, standard, performance")
    if data.get("eveng_environment_name") is not None and str(data.get("eveng_environment_name") or "").strip():
        require_non_empty_str(data.get("eveng_environment_name"), "inputs.eveng_environment_name")
    if data.get("eveng_domain") is not None and str(data.get("eveng_domain") or "").strip():
        require_non_empty_str(data.get("eveng_domain"), "inputs.eveng_domain")
    if data.get("eveng_force_reinstall") is not None:
        require_bool(data.get("eveng_force_reinstall"), "inputs.eveng_force_reinstall")
    guest_nat_enabled = require_bool(
        data.get("eveng_guest_nat_enabled"), "inputs.eveng_guest_nat_enabled"
    )
    if guest_nat_enabled:
        bridge = require_non_empty_str(
            data.get("eveng_guest_nat_bridge"), "inputs.eveng_guest_nat_bridge"
        )
        if not re.fullmatch(r"pnet[1-9]", bridge):
            raise ValueError(
                "inputs.eveng_guest_nat_bridge must be one of pnet1 through pnet9"
            )
        try:
            gateway = ipaddress.ip_interface(
                require_non_empty_str(
                    data.get("eveng_guest_nat_cidr"), "inputs.eveng_guest_nat_cidr"
                )
            )
            subnet = ipaddress.ip_network(
                require_non_empty_str(
                    data.get("eveng_guest_nat_subnet"),
                    "inputs.eveng_guest_nat_subnet",
                ),
                strict=True,
            )
            dhcp_start = ipaddress.ip_address(
                require_non_empty_str(
                    data.get("eveng_guest_nat_dhcp_start"),
                    "inputs.eveng_guest_nat_dhcp_start",
                )
            )
            dhcp_end = ipaddress.ip_address(
                require_non_empty_str(
                    data.get("eveng_guest_nat_dhcp_end"),
                    "inputs.eveng_guest_nat_dhcp_end",
                )
            )
        except ValueError as exc:
            raise ValueError(
                f"inputs EVE-NG guest NAT addressing is invalid: {exc}"
            ) from exc
        if gateway.network != subnet or gateway.ip not in subnet:
            raise ValueError(
                "inputs.eveng_guest_nat_cidr must belong to eveng_guest_nat_subnet"
            )
        if (
            dhcp_start not in subnet
            or dhcp_end not in subnet
            or int(dhcp_start) > int(dhcp_end)
        ):
            raise ValueError(
                "inputs EVE-NG guest NAT DHCP range must be ordered within the guest subnet"
            )
        if gateway.ip in {dhcp_start, dhcp_end}:
            raise ValueError(
                "inputs EVE-NG guest NAT gateway must not be a DHCP range endpoint"
            )
    _validate_users(data.get("eveng_users"))
