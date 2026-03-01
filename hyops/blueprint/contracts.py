"""Blueprint step contract and inputs materialization helpers."""

from __future__ import annotations

from pathlib import Path
from typing import Any
import os
import re
import ssl
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

import yaml

from hyops.runtime.module_state import read_module_state
from hyops.runtime.netbox_env import (
    hydrate_netbox_env,
    normalize_netbox_api_url,
    resolve_netbox_authority_root,
)

from .common import as_mapping, merge_mappings
from .constants import NETBOX_MODULE_REF


def _as_dict(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return dict(value)
    return {}


def _as_str_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    out: list[str] = []
    for item in value:
        token = str(item or "").strip()
        if token:
            out.append(token)
    return out


def probe_netbox_live_api(*, runtime_root: Path, env_map: dict[str, str], timeout_s: float = 5.0) -> str:
    probe_env: dict[str, str] = dict(env_map)
    warnings, missing = hydrate_netbox_env(probe_env, runtime_root)
    if missing:
        missing_csv = ", ".join(missing)
        warning_hint = ""
        if warnings:
            first = str(warnings[0] or "").strip()
            if first:
                warning_hint = f" ({first})"
        return (
            f"missing required NetBox env keys: {missing_csv}. "
            f"Run NetBox bootstrap and ensure NETBOX_API_URL/NETBOX_API_TOKEN are available{warning_hint}."
        )

    base_url = normalize_netbox_api_url(str(probe_env.get("NETBOX_API_URL") or ""))
    token = str(probe_env.get("NETBOX_API_TOKEN") or "").strip()
    if not base_url:
        return "NETBOX_API_URL is empty after hydration"
    if not token:
        return "NETBOX_API_TOKEN is empty after hydration"

    # Use an authenticated endpoint so token validity is also checked.
    probe_url = f"{base_url.rstrip('/')}/api/dcim/sites/?limit=1"
    req = Request(
        probe_url,
        headers={
            "Authorization": f"Token {token}",
            "Accept": "application/json",
        },
        method="GET",
    )
    ssl_ctx = ssl._create_unverified_context() if probe_url.startswith("https://") else None
    try:
        with urlopen(req, timeout=timeout_s, context=ssl_ctx) as resp:
            code = int(getattr(resp, "status", 0) or 0)
            if 200 <= code < 300:
                return ""
            return f"unexpected HTTP status from NetBox API: {code}"
    except HTTPError as exc:
        code = int(getattr(exc, "code", 0) or 0)
        if code in (401, 403):
            return "NETBOX_API_TOKEN is rejected by NetBox API"
        return f"NetBox API returned HTTP {code}"
    except URLError as exc:
        reason = str(getattr(exc, "reason", "") or "").strip() or str(exc)
        return f"NetBox API unreachable ({reason})"
    except Exception as exc:
        return f"NetBox API probe failed: {exc}"


def module_state_status(state_root: Path, module_ref: str) -> str:
    try:
        payload = read_module_state(state_root, module_ref)
    except Exception:
        return ""
    return str(payload.get("status") or "").strip().lower()


def module_state_ok(state_root: Path, module_ref: str) -> bool:
    return module_state_status(state_root, module_ref) == "ok"


def step_state_ref(step: dict[str, Any]) -> str:
    module_ref = str(step.get("module_ref") or "").strip()
    state_instance = str(step.get("state_instance") or "").strip().lower()
    if state_instance:
        return f"{module_ref}#{state_instance}"
    return module_ref


def load_inputs_file(path: Path, field: str) -> dict[str, Any]:
    payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return as_mapping(payload, field)


def resolved_step_inputs_file(step: dict[str, Any], payload: dict[str, Any], paths) -> Path | None:
    inline_inputs = step.get("inputs") if isinstance(step.get("inputs"), dict) else None
    inputs_file_ref = str(step.get("inputs_file") or "").strip()

    file_inputs: dict[str, Any] = {}
    resolved_file: Path | None = None
    if inputs_file_ref:
        candidate = Path(inputs_file_ref).expanduser()
        if not candidate.is_absolute():
            candidate = (Path(payload["path"]).resolve().parent / candidate).resolve()
        if not candidate.exists():
            raise FileNotFoundError(
                f"step '{step['id']}' inputs_file not found: {candidate}"
            )
        file_inputs = load_inputs_file(candidate, f"steps.{step['id']}.inputs_file")
        resolved_file = candidate

    if inline_inputs is None:
        return resolved_file

    merged = merge_mappings(file_inputs, inline_inputs)
    bp_token = re.sub(r"[^A-Za-z0-9_.-]+", "_", payload["blueprint_ref"])
    out_dir = paths.work_dir / "blueprint-inputs" / bp_token
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = (out_dir / f"{step['id']}.inputs.yml").resolve()
    out_path.write_text(yaml.safe_dump(merged, sort_keys=False), encoding="utf-8")
    os.chmod(out_path, 0o600)
    return out_path


def enforce_step_contracts(
    step: dict[str, Any],
    payload: dict[str, Any],
    paths,
    *,
    assumed_state_ok: set[str] | None = None,
) -> None:
    contracts = _as_dict(step.get("contracts"))
    policy = _as_dict(payload.get("policy"))
    assumed = set(assumed_state_ok or set())
    strict_live_check = bool(policy.get("netbox_live_api_check", False))

    def state_ok(module_ref: str) -> bool:
        return module_ref in assumed or module_state_ok(paths.state_dir, module_ref)

    def state_status(module_ref: str) -> str:
        if module_ref in assumed:
            return "planned-ok"
        return module_state_status(paths.state_dir, module_ref) or "missing"

    # NetBox can be centralized in a different env/root (SSOT pattern).
    netbox_state_dir = paths.state_dir
    env_map: dict[str, str] = {str(k): str(v) for k, v in os.environ.items()}
    authority_root, authority_err = resolve_netbox_authority_root(env_map, paths.root)
    if authority_err:
        raise ValueError(f"invalid netbox authority config: {authority_err}")
    if authority_root:
        netbox_state_dir = (authority_root / "state").resolve()

    def netbox_state_ok() -> bool:
        return NETBOX_MODULE_REF in assumed or module_state_ok(netbox_state_dir, NETBOX_MODULE_REF)

    def netbox_state_status() -> str:
        if NETBOX_MODULE_REF in assumed:
            return "planned-ok"
        return module_state_status(netbox_state_dir, NETBOX_MODULE_REF) or "missing"

    requires_module_state_ok = _as_str_list(contracts.get("requires_module_state_ok"))
    for module_ref in requires_module_state_ok:
        if not state_ok(module_ref):
            status = state_status(module_ref)
            raise ValueError(
                f"contract failed: required module state is not ok "
                f"({module_ref}, status={status})"
            )

    ipam_authority = str(policy.get("ipam_authority") or "none").strip().lower()
    requires_authority = str(contracts.get("requires_authority") or "none").strip().lower()
    requires_netbox_authority = False
    if requires_authority == "netbox":
        requires_netbox_authority = True
        if ipam_authority != "netbox":
            raise ValueError(
                "contract failed: requires_authority=netbox but policy.ipam_authority is not netbox"
            )
        if not netbox_state_ok():
            status = netbox_state_status()
            authority_hint = f" (authority_root={authority_root})" if authority_root else ""
            raise ValueError(
                f"contract failed: netbox authority not ready "
                f"({NETBOX_MODULE_REF}, status={status}){authority_hint}"
            )

    addressing_mode = str(contracts.get("addressing_mode") or "static").strip().lower()
    requires_netbox_ipam = False
    if addressing_mode == "ipam":
        requires_netbox_ipam = True
        if ipam_authority != "netbox":
            raise ValueError(
                "contract failed: addressing_mode=ipam requires policy.ipam_authority=netbox"
            )
        if not netbox_state_ok():
            status = netbox_state_status()
            authority_hint = f" (authority_root={authority_root})" if authority_root else ""
            raise ValueError(
                f"contract failed: addressing_mode=ipam requires netbox state ok "
                f"({NETBOX_MODULE_REF}, status={status}){authority_hint}"
            )

    if strict_live_check and (requires_netbox_authority or requires_netbox_ipam):
        probe_env = dict(env_map)
        if authority_root:
            probe_env.setdefault("HYOPS_NETBOX_AUTHORITY_ROOT", str(authority_root))
        probe_err = probe_netbox_live_api(runtime_root=paths.root, env_map=probe_env, timeout_s=5.0)
        if probe_err:
            authority_hint = f" (authority_root={authority_root})" if authority_root else ""
            raise ValueError(
                "contract failed: netbox live api check failed: "
                f"{probe_err}{authority_hint}. "
                "Set policy.netbox_live_api_check=false to use state-only authority checks."
            )
