"""hyops.validators.platform.network.cloudflare_traffic_steering

purpose: Validate inputs for platform/network/cloudflare-traffic-steering module.
maintainer: HybridOps
"""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import urlparse

from hyops.validators.common import (
    normalize_required_env,
    opt_bool,
    opt_int,
    opt_str,
    opt_str_list,
    require_non_empty_str,
)
from hyops.validators.registry import ModuleValidationError

_FQDN_RE = re.compile(
    r"^(?=.{1,253}$)([A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?)(\.[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?)*\.?$"
)
_ENV_RE = re.compile(r"[A-Z_][A-Z0-9_]*")


def _require_fqdn(value: Any, field: str) -> str:
    token = require_non_empty_str(value, field)
    if not _FQDN_RE.fullmatch(token):
        raise ModuleValidationError(f"{field} must be a valid hostname")
    return token.rstrip(".")


def _require_url(value: Any, field: str) -> str:
    token = require_non_empty_str(value, field)
    parsed = urlparse(token)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ModuleValidationError(f"{field} must be a valid http or https URL")
    if parsed.path not in {"", "/"}:
        raise ModuleValidationError(f"{field} must not include a path; route paths are forwarded from the public host")
    return token.rstrip("/")


def _require_env_name(value: Any, field: str) -> str:
    token = require_non_empty_str(value, field)
    if not _ENV_RE.fullmatch(token):
        raise ModuleValidationError(f"{field} must be a valid environment variable name")
    return token


def _validate_prefixes(prefixes: list[str], field: str) -> list[str]:
    if not prefixes:
        raise ModuleValidationError(f"{field} must be a non-empty list")
    out: list[str] = []
    for idx, item in enumerate(prefixes, start=1):
        token = require_non_empty_str(item, f"{field}[{idx}]")
        if not token.startswith("/"):
            raise ModuleValidationError(f"{field}[{idx}] must start with '/'")
        out.append(token.rstrip("/") if token != "/" else "/")
    return out


def validate(inputs: dict[str, Any]) -> None:
    data = inputs or {}
    if not isinstance(data, dict):
        raise ModuleValidationError("inputs must be a mapping")

    steering_state = require_non_empty_str(data.get("steering_state") or "present", "inputs.steering_state").lower()
    if steering_state not in {"present", "absent"}:
        raise ModuleValidationError("inputs.steering_state must be one of: present, absent")

    apply_mode = require_non_empty_str(data.get("apply_mode") or "bootstrap", "inputs.apply_mode").lower()
    if apply_mode not in {"bootstrap", "status"}:
        raise ModuleValidationError("inputs.apply_mode must be one of: bootstrap, status")
    if steering_state == "absent" and apply_mode == "status":
        raise ModuleValidationError("inputs.apply_mode=status requires inputs.steering_state=present")

    token_env = _require_env_name(data.get("cloudflare_api_token_env"), "inputs.cloudflare_api_token_env")
    required_env = normalize_required_env(data.get("required_env"), "inputs.required_env")

    if apply_mode == "bootstrap" or steering_state == "absent":
        if token_env not in required_env:
            raise ModuleValidationError(f"inputs.required_env must include '{token_env}'")

    _require_fqdn(data.get("zone_name"), "inputs.zone_name")
    hostname = _require_fqdn(data.get("hostname"), "inputs.hostname")
    route_pattern = opt_str(data.get("route_pattern"), "inputs.route_pattern")
    if route_pattern:
        if route_pattern != f"{hostname}/*":
            raise ModuleValidationError("inputs.route_pattern must match '<hostname>/*'")
    require_non_empty_str(data.get("worker_name"), "inputs.worker_name")
    require_non_empty_str(data.get("compatibility_date"), "inputs.compatibility_date")

    ensure_dns_record = bool(opt_bool(data.get("ensure_dns_record"), "inputs.ensure_dns_record", default=False))
    if ensure_dns_record:
        record_type = require_non_empty_str(data.get("dns_record_type") or "CNAME", "inputs.dns_record_type").upper()
        if record_type not in {"A", "AAAA", "CNAME"}:
            raise ModuleValidationError("inputs.dns_record_type must be one of: A, AAAA, CNAME")
        record_name = _require_fqdn(data.get("dns_record_name"), "inputs.dns_record_name")
        if record_name != hostname:
            raise ModuleValidationError("inputs.dns_record_name must match inputs.hostname")
        require_non_empty_str(data.get("dns_record_target"), "inputs.dns_record_target")
        dns_record_proxied = opt_bool(data.get("dns_record_proxied"), "inputs.dns_record_proxied", default=True)
        if dns_record_proxied is None:
            raise ModuleValidationError("inputs.dns_record_proxied must be set")

    desired = require_non_empty_str(data.get("desired") or "primary", "inputs.desired").lower()
    if desired not in {"primary", "balanced", "burst"}:
        raise ModuleValidationError("inputs.desired must be one of: primary, balanced, burst")

    balanced_weight = opt_int(
        data.get("balanced_burst_weight_pct"),
        "inputs.balanced_burst_weight_pct",
        minimum=1,
    )
    if balanced_weight is None:
        raise ModuleValidationError("inputs.balanced_burst_weight_pct must be set")
    if balanced_weight >= 100:
        raise ModuleValidationError("inputs.balanced_burst_weight_pct must be < 100")

    _require_url(data.get("primary_origin_url"), "inputs.primary_origin_url")
    _require_url(data.get("burst_origin_url"), "inputs.burst_origin_url")

    cookie_name = require_non_empty_str(data.get("cookie_name"), "inputs.cookie_name")
    if "=" in cookie_name or ";" in cookie_name:
        raise ModuleValidationError("inputs.cookie_name must be cookie-safe")
    cookie_ttl_s = opt_int(data.get("cookie_ttl_s"), "inputs.cookie_ttl_s", minimum=1)
    if cookie_ttl_s is None:
        raise ModuleValidationError("inputs.cookie_ttl_s must be set")

    root_redirect_path = require_non_empty_str(data.get("root_redirect_path"), "inputs.root_redirect_path")
    if not root_redirect_path.startswith("/"):
        raise ModuleValidationError("inputs.root_redirect_path must start with '/'")

    prefixes = _validate_prefixes(
        opt_str_list(data.get("forward_prefixes"), "inputs.forward_prefixes"),
        "inputs.forward_prefixes",
    )
    if root_redirect_path.rstrip("/") not in {item.rstrip("/") for item in prefixes}:
        raise ModuleValidationError("inputs.forward_prefixes must include inputs.root_redirect_path")

    status_timeout_s = opt_int(data.get("status_timeout_s"), "inputs.status_timeout_s", minimum=1)
    status_retries = opt_int(data.get("status_retries"), "inputs.status_retries", minimum=1)
    status_retry_delay_s = opt_int(data.get("status_retry_delay_s"), "inputs.status_retry_delay_s", minimum=1)
    if status_timeout_s is None or status_retries is None or status_retry_delay_s is None:
        raise ModuleValidationError("status timing inputs must be set")
