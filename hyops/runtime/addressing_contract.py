"""Addressing contract validation for module inputs.

purpose: Enforce a stable addressing input contract before driver execution.
Architecture Decision: ADR-N/A (addressing contract)
maintainer: HybridOps.Studio
"""

from __future__ import annotations

from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen
import os

from hyops.runtime.coerce import as_bool


def _normalize_netbox_api_url(raw: str) -> str:
    v = str(raw or "").strip()
    if not v:
        return ""
    v = v.rstrip("/")
    # Accept both http://netbox:8000 and http://netbox:8000/api as inputs.
    if v.endswith("/api"):
        v = v[:-4]
    return v


def _probe_netbox_api(api_url: str, api_token: str) -> None:
    base_url = _normalize_netbox_api_url(api_url)
    parsed = urlparse(base_url)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise ValueError("NETBOX_API_URL must be an absolute http(s) URL")

    timeout_s = 5.0
    timeout_raw = str(os.environ.get("HYOPS_NETBOX_PROBE_TIMEOUT_S") or "").strip()
    if timeout_raw:
        try:
            timeout_s = max(float(timeout_raw), 1.0)
        except Exception as exc:
            raise ValueError("HYOPS_NETBOX_PROBE_TIMEOUT_S must be a number") from exc

    endpoint = f"{base_url}/api/dcim/sites/?limit=1"
    req = Request(
        endpoint,
        method="GET",
        headers={
            "Authorization": f"Token {api_token}",
            "Accept": "application/json",
        },
    )

    try:
        with urlopen(req, timeout=timeout_s) as resp:
            status = int(getattr(resp, "status", 0))
            if status < 200 or status >= 300:
                raise ValueError(f"NetBox API probe failed with HTTP {status}")
    except HTTPError as exc:
        if exc.code in (401, 403):
            raise ValueError("NETBOX_API_TOKEN is rejected by NetBox API") from exc
        raise ValueError(f"NetBox API probe failed with HTTP {exc.code}") from exc
    except URLError as exc:
        reason = str(getattr(exc, "reason", "") or "unreachable").strip()
        raise ValueError(f"NetBox API probe failed: {reason}") from exc
    except TimeoutError as exc:
        raise ValueError("NetBox API probe timed out") from exc


def validate_addressing_contract(inputs: dict[str, Any]) -> None:
    raw_addressing = inputs.get("addressing")
    if raw_addressing is None:
        return

    if not isinstance(raw_addressing, dict):
        raise ValueError("inputs.addressing must be a mapping when set")

    allowed_keys = {"mode", "ipam"}
    unknown_keys = sorted([str(k) for k in raw_addressing.keys() if str(k) not in allowed_keys])
    if unknown_keys:
        raise ValueError(f"inputs.addressing has unknown keys: {', '.join(unknown_keys)}")

    mode = str(raw_addressing.get("mode") or "").strip().lower()
    if mode not in ("static", "ipam"):
        raise ValueError("inputs.addressing.mode must be one of: static, ipam")

    raw_ipam = raw_addressing.get("ipam")
    if mode == "static":
        if raw_ipam not in (None, {}):
            raise ValueError("inputs.addressing.ipam is only allowed when inputs.addressing.mode=ipam")
        return

    if not isinstance(raw_ipam, dict):
        raise ValueError("inputs.addressing.ipam must be a mapping when inputs.addressing.mode=ipam")

    # Keep this forward-compatible: allow provider-specific hinting without breaking
    # the input contract.
    ipam_allowed_keys = {
        "provider",
        # Optional: module state references or connectivity hints used by contracts/drivers.
        "network_state_ref",
        "ssh_proxy_jump_host",
        "ssh_proxy_jump_user",
        "ssh_proxy_jump_key_file",
    }
    ipam_unknown_keys = sorted([str(k) for k in raw_ipam.keys() if str(k) not in ipam_allowed_keys])
    if ipam_unknown_keys:
        raise ValueError(f"inputs.addressing.ipam has unknown keys: {', '.join(ipam_unknown_keys)}")

    provider = str(raw_ipam.get("provider") or "").strip().lower()
    if provider != "netbox":
        raise ValueError("inputs.addressing.ipam.provider must be 'netbox' when inputs.addressing.mode=ipam")

    # NETBOX_* vars can be hydrated from runtime state/vault by drivers. Only
    # probe when present in the current process env.
    api_url = _normalize_netbox_api_url(os.environ.get("NETBOX_API_URL") or "")
    api_token = str(os.environ.get("NETBOX_API_TOKEN") or "").strip()
    if not api_url or not api_token:
        return

    if as_bool(os.environ.get("HYOPS_SKIP_NETBOX_PROBE"), default=False):
        return

    _probe_netbox_api(api_url, api_token)
