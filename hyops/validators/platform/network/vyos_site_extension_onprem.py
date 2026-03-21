"""hyops.validators.platform.network.vyos_site_extension_onprem

purpose: Validate inputs for platform/network/vyos-site-extension-onprem module.
maintainer: HybridOps.Tech
"""

from __future__ import annotations

import ipaddress
from typing import Any

from hyops.validators.common import require_port as _require_port


def _require_non_empty_str(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be a non-empty string")
    token = value.strip()
    marker = token.upper()
    if marker.startswith("CHANGE_ME") or "CHANGE_ME_" in marker:
        raise ValueError(f"{field} must not contain placeholder values (found {token!r})")
    return token


def _require_asn(value: Any, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{field} must be an integer")
    if value < 1 or value > 4294967294:
        raise ValueError(f"{field} must be in range 1..4294967294")
    return value


def _require_ipv4(value: Any, field: str) -> str:
    token = _require_non_empty_str(value, field)
    try:
        ip = ipaddress.ip_address(token)
    except Exception as exc:
        raise ValueError(f"{field} must be a valid IPv4 address") from exc
    if not isinstance(ip, ipaddress.IPv4Address):
        raise ValueError(f"{field} must be a valid IPv4 address")
    return token


def _require_cidr_list(value: Any, field: str, *, allow_empty: bool = False) -> list[str]:
    if not isinstance(value, list):
        raise ValueError(f"{field} must be a list")
    if not value and not allow_empty:
        raise ValueError(f"{field} must be a non-empty list")
    out: list[str] = []
    for idx, item in enumerate(value, start=1):
        token = _require_non_empty_str(item, f"{field}[{idx}]")
        try:
            ipaddress.ip_network(token, strict=False)
        except Exception as exc:
            raise ValueError(f"{field}[{idx}] must be a valid CIDR") from exc
        out.append(token)
    return out


def validate(inputs: dict[str, Any]) -> None:
    data = inputs or {}
    if not isinstance(data, dict):
        raise ValueError("inputs must be a mapping")

    target_host = str(data.get("target_host") or "").strip()
    target_state_ref = str(data.get("target_state_ref") or "").strip()
    if not target_host and not target_state_ref:
        raise ValueError("inputs.target_host or inputs.target_state_ref is required")
    if target_state_ref:
        _require_non_empty_str(target_state_ref, "inputs.target_state_ref")
        _require_non_empty_str(data.get("target_vm_key"), "inputs.target_vm_key")

    required_env = data.get("required_env")
    if not isinstance(required_env, list) or not required_env:
        raise ValueError("inputs.required_env must be a non-empty list")
    psk_env = _require_non_empty_str(data.get("site_extension_psk_env"), "inputs.site_extension_psk_env")
    if psk_env not in required_env:
        raise ValueError(
            f"inputs.required_env must include: {psk_env} (referenced by inputs.site_extension_psk_env)"
        )

    state = _require_non_empty_str(data.get("vyos_site_extension_state"), "inputs.vyos_site_extension_state").lower()
    if state not in {"present", "absent"}:
        raise ValueError("inputs.vyos_site_extension_state must be 'present' or 'absent'")

    _require_non_empty_str(data.get("vyos_site_extension_onprem_role_fqcn"), "inputs.vyos_site_extension_onprem_role_fqcn")
    target_user = str(data.get("target_user") or "").strip()
    onprem_ssh_user = _require_non_empty_str(data.get("onprem_ssh_user"), "inputs.onprem_ssh_user")
    if target_user and target_user != onprem_ssh_user:
        raise ValueError(
            "inputs.target_user must match inputs.onprem_ssh_user for consistent Ansible driver preflight"
        )
    if data.get("onprem_ssh_port") is not None:
        onprem_ssh_port = _require_port(data.get("onprem_ssh_port"), "inputs.onprem_ssh_port")
        if data.get("target_port") is not None and int(data.get("target_port")) != onprem_ssh_port:
            raise ValueError(
                "inputs.target_port must match inputs.onprem_ssh_port for consistent Ansible driver preflight"
            )

    key_file = str(data.get("onprem_ssh_key_file") or "").strip()
    key_env = str(data.get("onprem_ssh_private_key_env") or "").strip()
    generic_key_file = str(data.get("ssh_private_key_file") or "").strip()
    if generic_key_file and key_file and generic_key_file != key_file:
        raise ValueError(
            "inputs.ssh_private_key_file must match inputs.onprem_ssh_key_file for consistent Ansible driver preflight"
        )
    if not key_file and not key_env:
        raise ValueError(
            "one of inputs.onprem_ssh_key_file or inputs.onprem_ssh_private_key_env must be set "
            "for localhost -> on-prem VyOS authentication"
        )

    _require_non_empty_str(data.get("onprem_local_id"), "inputs.onprem_local_id")
    _require_non_empty_str(data.get("onprem_local_address"), "inputs.onprem_local_address")
    _require_non_empty_str(data.get("onprem_bind_interface"), "inputs.onprem_bind_interface")
    if str(data.get("public_peer_route_next_hop") or "").strip():
        _require_ipv4(data.get("public_peer_route_next_hop"), "inputs.public_peer_route_next_hop")

    advertise_prefixes = _require_cidr_list(data.get("advertise_prefixes"), "inputs.advertise_prefixes", allow_empty=True)
    static_route_prefixes = _require_cidr_list(data.get("static_route_prefixes"), "inputs.static_route_prefixes", allow_empty=True)
    for prefix in static_route_prefixes:
        if prefix not in advertise_prefixes:
            raise ValueError(
                f"inputs.static_route_prefixes contains {prefix!r}, but it is not present in inputs.advertise_prefixes"
            )
    if static_route_prefixes:
        _require_ipv4(data.get("internal_route_next_hop"), "inputs.internal_route_next_hop")

    _require_ipv4(data.get("edge01_public_ip"), "inputs.edge01_public_ip")
    _require_ipv4(data.get("edge02_public_ip"), "inputs.edge02_public_ip")
    if str(data.get("edge01_remote_id") or "").strip():
        _require_non_empty_str(data.get("edge01_remote_id"), "inputs.edge01_remote_id")
    if str(data.get("edge02_remote_id") or "").strip():
        _require_non_empty_str(data.get("edge02_remote_id"), "inputs.edge02_remote_id")

    _require_ipv4(data.get("edge01_inside_local_ip"), "inputs.edge01_inside_local_ip")
    _require_ipv4(data.get("edge01_inside_peer_ip"), "inputs.edge01_inside_peer_ip")
    _require_ipv4(data.get("edge02_inside_local_ip"), "inputs.edge02_inside_local_ip")
    _require_ipv4(data.get("edge02_inside_peer_ip"), "inputs.edge02_inside_peer_ip")
    _require_ipv4(data.get("onprem_router_id"), "inputs.onprem_router_id")

    if data.get("inside_prefix_len") is None:
        raise ValueError("inputs.inside_prefix_len is required")
    if isinstance(data.get("inside_prefix_len"), bool) or not isinstance(data.get("inside_prefix_len"), int):
        raise ValueError("inputs.inside_prefix_len must be an integer")
    if int(data.get("inside_prefix_len")) != 30:
        raise ValueError("inputs.inside_prefix_len must be 30")

    _require_asn(data.get("local_asn"), "inputs.local_asn")
    _require_asn(data.get("peer_asn"), "inputs.peer_asn")

    for field in (
        "inputs.cloud_core_cidr",
        "inputs.cloud_workloads_cidr",
        "inputs.cloud_workloads_pods_cidr",
    ):
        raw = data.get(field.removeprefix("inputs."))
        if raw is None or str(raw).strip() == "":
            continue
        try:
            ipaddress.ip_network(str(raw).strip(), strict=False)
        except Exception as exc:
            raise ValueError(f"{field} must be a valid CIDR when set") from exc

    for field in (
        "auto_include_cloud_core_cidr_in_import",
        "auto_include_cloud_workloads_cidr_in_import",
        "auto_include_cloud_workloads_pods_cidr_in_import",
        "consumer_snat_translation_address_from_onprem_router_id",
        "auto_include_cloud_core_cidr_in_consumer_snat_source",
        "auto_include_cloud_workloads_cidr_in_consumer_snat_source",
        "auto_include_cloud_workloads_pods_cidr_in_consumer_snat_source",
        "auto_include_static_route_prefixes_in_consumer_snat_destination",
    ):
        if field in data and not isinstance(data.get(field), bool):
            raise ValueError(f"inputs.{field} must be a boolean when set")

    _require_cidr_list(data.get("import_allow_prefixes"), "inputs.import_allow_prefixes", allow_empty=True)

    if "consumer_snat_enabled" in data and not isinstance(data.get("consumer_snat_enabled"), bool):
        raise ValueError("inputs.consumer_snat_enabled must be a boolean when set")
    if data.get("consumer_snat_enabled"):
        if isinstance(data.get("consumer_snat_rule_base"), bool) or not isinstance(data.get("consumer_snat_rule_base"), int):
            raise ValueError("inputs.consumer_snat_rule_base must be an integer when consumer SNAT is enabled")
        if isinstance(data.get("consumer_snat_rule_slots"), bool) or not isinstance(data.get("consumer_snat_rule_slots"), int):
            raise ValueError("inputs.consumer_snat_rule_slots must be an integer when consumer SNAT is enabled")
        if int(data.get("consumer_snat_rule_base")) <= 0:
            raise ValueError("inputs.consumer_snat_rule_base must be greater than zero when consumer SNAT is enabled")
        if int(data.get("consumer_snat_rule_slots")) <= 0:
            raise ValueError("inputs.consumer_snat_rule_slots must be greater than zero when consumer SNAT is enabled")

        effective_sources = _require_cidr_list(
            data.get("consumer_snat_source_cidrs"), "inputs.consumer_snat_source_cidrs", allow_empty=True
        )
        effective_destinations = _require_cidr_list(
            data.get("consumer_snat_destination_cidrs"), "inputs.consumer_snat_destination_cidrs", allow_empty=True
        )

        if data.get("auto_include_cloud_core_cidr_in_consumer_snat_source") and str(data.get("cloud_core_cidr") or "").strip():
            effective_sources.append(str(data.get("cloud_core_cidr")).strip())
        if data.get("auto_include_cloud_workloads_cidr_in_consumer_snat_source") and str(data.get("cloud_workloads_cidr") or "").strip():
            effective_sources.append(str(data.get("cloud_workloads_cidr")).strip())
        if data.get("auto_include_cloud_workloads_pods_cidr_in_consumer_snat_source") and str(data.get("cloud_workloads_pods_cidr") or "").strip():
            effective_sources.append(str(data.get("cloud_workloads_pods_cidr")).strip())
        if data.get("auto_include_static_route_prefixes_in_consumer_snat_destination"):
            effective_destinations.extend(static_route_prefixes)

        effective_sources = list(dict.fromkeys(effective_sources))
        effective_destinations = list(dict.fromkeys(effective_destinations))

        if not effective_sources:
            raise ValueError("consumer SNAT is enabled but no effective source CIDRs are configured")
        if not effective_destinations:
            raise ValueError("consumer SNAT is enabled but no effective destination CIDRs are configured")

        translation_address = str(data.get("consumer_snat_translation_address") or "").strip()
        if translation_address:
            _require_ipv4(translation_address, "inputs.consumer_snat_translation_address")
        elif not data.get("consumer_snat_translation_address_from_onprem_router_id"):
            raise ValueError(
                "consumer SNAT is enabled but inputs.consumer_snat_translation_address is empty and "
                "inputs.consumer_snat_translation_address_from_onprem_router_id is false"
            )

        _require_non_empty_str(data.get("consumer_snat_outbound_interface"), "inputs.consumer_snat_outbound_interface")

        if len(effective_sources) * len(effective_destinations) > int(data.get("consumer_snat_rule_slots")):
            raise ValueError("effective consumer SNAT rule count exceeds inputs.consumer_snat_rule_slots")

    _require_non_empty_str(data.get("ipsec_ike_group"), "inputs.ipsec_ike_group")
    _require_non_empty_str(data.get("ipsec_esp_group"), "inputs.ipsec_esp_group")
    _require_non_empty_str(data.get("bgp_export_prefix_list"), "inputs.bgp_export_prefix_list")
    _require_non_empty_str(data.get("bgp_import_prefix_list"), "inputs.bgp_import_prefix_list")
    _require_non_empty_str(data.get("bgp_export_route_map"), "inputs.bgp_export_route_map")
    _require_non_empty_str(data.get("bgp_import_route_map"), "inputs.bgp_import_route_map")

    if data.get("validate_post_apply") is not None and not isinstance(data.get("validate_post_apply"), bool):
        raise ValueError("inputs.validate_post_apply must be a boolean when set")
