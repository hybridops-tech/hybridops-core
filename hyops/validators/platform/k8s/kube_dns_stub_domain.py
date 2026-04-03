"""
purpose: Validate inputs for platform/k8s/kube-dns-stub-domain module.
maintainer: HybridOps.Tech
"""

from __future__ import annotations

import ipaddress
import re
from typing import Any

from hyops.validators.common import check_no_placeholder, normalize_lifecycle_command, opt_str, require_non_empty_str
from hyops.validators.registry import ModuleValidationError

_FQDN_RE = re.compile(r"^(?=.{1,253}$)([A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?)(\.[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?)*\.?$")


def _req_str(inputs: dict[str, Any], key: str) -> str:
    return check_no_placeholder(
        require_non_empty_str(inputs.get(key), f"inputs.{key}"),
        f"inputs.{key}",
    )


def _opt_str(inputs: dict[str, Any], key: str) -> str:
    value = opt_str(inputs.get(key), f"inputs.{key}")
    return check_no_placeholder(value, f"inputs.{key}") if value else value


def validate(inputs: dict[str, Any]) -> None:
    lifecycle = normalize_lifecycle_command(inputs)

    raw_kube_state_ref = _opt_str(inputs, "kubeconfig_state_ref")
    raw_kube_path = _opt_str(inputs, "kubeconfig_path")
    if not raw_kube_state_ref and not raw_kube_path:
        raise ModuleValidationError("inputs.kubeconfig_path or inputs.kubeconfig_state_ref is required")

    _req_str(inputs, "namespace")
    _req_str(inputs, "configmap_name")
    stub_domain = _req_str(inputs, "stub_domain").rstrip(".")
    if not _FQDN_RE.fullmatch(stub_domain):
        raise ModuleValidationError("inputs.stub_domain must be a valid DNS suffix")
    _req_str(inputs, "kubectl_bin")

    powerdns_state_ref = _opt_str(inputs, "powerdns_state_ref")
    _opt_str(inputs, "powerdns_state_env")

    raw_servers = inputs.get("dns_server_ips") or []
    if raw_servers and not isinstance(raw_servers, list):
        raise ModuleValidationError("inputs.dns_server_ips must be a list when set")
    for idx, item in enumerate(raw_servers, start=1):
        token = check_no_placeholder(
            require_non_empty_str(item, f"inputs.dns_server_ips[{idx}]"),
            f"inputs.dns_server_ips[{idx}]",
        )
        try:
            ipaddress.ip_address(token)
        except ValueError as exc:
            raise ModuleValidationError(
                f"inputs.dns_server_ips[{idx}] must be a valid IPv4 or IPv6 address"
            ) from exc

    if lifecycle != "destroy" and not raw_servers and not powerdns_state_ref:
        raise ModuleValidationError(
            "inputs.dns_server_ips or inputs.powerdns_state_ref is required"
        )
