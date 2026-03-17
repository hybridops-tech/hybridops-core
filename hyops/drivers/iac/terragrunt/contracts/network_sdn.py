"""
purpose: Module contract for core/onprem/network-sdn Terragrunt behavior.
Architecture Decision: ADR-N/A (terragrunt network-sdn contract)
maintainer: HybridOps.Tech
"""

from __future__ import annotations

import re
import ssl
import os
from pathlib import Path
from typing import Any
from urllib import error as url_error
from urllib import request as url_request

from hyops.runtime.module_state import read_module_state
from hyops.runtime.naming import compose_compact_id, compose_label, resolve_env_code
from hyops.runtime.credentials import parse_tfvars
from hyops.runtime.netbox_env import resolve_netbox_authority_root
from hyops.runtime.coerce import as_bool

from .base import TerragruntModuleContract


_PROXMOX_SDN_ID_RE = re.compile(r"^[a-z][a-z0-9]{0,7}$")


def _proxmox_base_url(tfvars: dict[str, str]) -> str:
    raw = str(tfvars.get("proxmox_url") or "").strip()
    if not raw:
        return ""
    return raw[:-len("/api2/json")] if raw.endswith("/api2/json") else raw


def _proxmox_zone_exists(
    *,
    tfvars: dict[str, str],
    zone_name: str,
) -> tuple[bool, str]:
    base = _proxmox_base_url(tfvars)
    token_id = str(tfvars.get("proxmox_token_id") or "").strip()
    token_secret = str(tfvars.get("proxmox_token_secret") or "").strip()
    if not base or not token_id or not token_secret:
        return False, "missing proxmox_url/proxmox_token_id/proxmox_token_secret in proxmox credentials"

    zone = str(zone_name or "").strip()
    if not zone:
        return False, "missing inputs.zone_name"

    url = f"{base}/api2/json/cluster/sdn/zones/{zone}"
    headers = {"Authorization": f"PVEAPIToken={token_id}={token_secret}"}
    req = url_request.Request(url=url, headers=headers, method="GET")

    skip_tls_raw = str(tfvars.get("proxmox_skip_tls") or "").strip().lower()
    skip_tls = skip_tls_raw in ("1", "true", "yes", "on")
    context = ssl._create_unverified_context() if skip_tls else ssl.create_default_context()

    try:
        with url_request.urlopen(req, timeout=10, context=context) as resp:
            _ = resp.read()
        return True, ""
    except url_error.HTTPError as exc:
        body = ""
        try:
            body = exc.read().decode("utf-8", errors="ignore")
        except Exception:
            body = ""
        text = f"{exc.reason} {body}".lower()
        if exc.code == 404:
            return False, ""
        if "does not exist" in text or "no such" in text or "not found" in text:
            return False, ""
        return False, f"failed to query Proxmox SDN zone '{zone}': HTTP {exc.code} {exc.reason}"
    except Exception as exc:
        return False, f"failed to query Proxmox SDN zone '{zone}': {exc}"


def _network_sdn_zone_conflict_strategy(inputs: dict[str, Any]) -> str:
    raw = str(inputs.get("zone_conflict_strategy") or "fail").strip().lower()
    if raw in ("", "fail"):
        return "fail"
    raise ValueError("inputs.zone_conflict_strategy must be: fail")


def _owned_network_sdn_zone_name(
    *,
    state_dir: str,
    module_ref: str,
) -> tuple[str, str]:
    root = Path(str(state_dir or "")).expanduser().resolve()
    if not str(root):
        return "", "runtime.state_dir is required for SDN ownership checks"

    try:
        payload = read_module_state(root, module_ref)
    except FileNotFoundError:
        return "", ""
    except Exception as exc:
        return "", f"failed to read module state for SDN ownership checks: {exc}"

    outputs = payload.get("outputs")
    if not isinstance(outputs, dict):
        return "", ""
    return str(outputs.get("zone_name") or "").strip(), ""


def _netbox_state_ready(*, state_dir: str) -> tuple[bool, str]:
    state_root = Path(str(state_dir or "")).expanduser().resolve()
    if not str(state_root):
        return False, "runtime.state_dir is required for NetBox state checks"

    # Support centralized NetBox in a different env/root.
    env_map: dict[str, str] = {str(k): str(v) for k, v in os.environ.items()}
    runtime_root = state_root.parent if state_root.name == "state" else state_root
    authority_root, authority_err = resolve_netbox_authority_root(env_map, runtime_root)
    if authority_err:
        return False, f"invalid netbox authority config: {authority_err}"

    if authority_root:
        state_root = (authority_root / "state").resolve()

    netbox_ref = "platform/onprem/netbox"
    try:
        payload = read_module_state(state_root, netbox_ref)
    except FileNotFoundError:
        authority_hint = ""
        if authority_root:
            authority_hint = f" (authority_root={authority_root})"
        return False, (
            "push_to_netbox requires module state for platform/onprem/netbox; "
            "run NetBox first (or set HYOPS_NETBOX_AUTHORITY_ENV / HYOPS_NETBOX_AUTHORITY_ROOT) "
            f"or set execution.hooks.export_infra.push_to_netbox=false{authority_hint}"
        )
    except Exception as exc:
        return False, f"failed to read NetBox module state: {exc}"

    status = str(payload.get("status") or "").strip().lower()
    if status != "ok":
        return False, (
            "push_to_netbox requires platform/onprem/netbox state status=ok; "
            f"current status={status or 'unknown'}"
        )

    return True, ""


class NetworkSdnContract(TerragruntModuleContract):
    def preprocess_inputs(
        self,
        *,
        command_name: str,
        module_ref: str,
        inputs: dict[str, Any],
        profile_policy: dict[str, Any],
        runtime: dict[str, Any],
        env: dict[str, str],
        credential_env: dict[str, str],
    ) -> tuple[dict[str, Any], list[str], str]:
        normalized_command = str(command_name or "").strip().lower()
        if normalized_command == "import":
            return inputs, [], ""

        try:
            _ = _network_sdn_zone_conflict_strategy(inputs)
        except Exception as exc:
            return inputs, [], str(exc)

        next_inputs = dict(inputs)
        if "zone_conflict_strategy" in next_inputs:
            next_inputs.pop("zone_conflict_strategy", None)

        warnings: list[str] = []
        base_zone_name = str(next_inputs.get("zone_name") or "").strip()
        zone_name = base_zone_name

        env_name = ""
        if isinstance(runtime, dict):
            env_name = str(runtime.get("env") or "").strip()
        if not env_name:
            env_name = str(env.get("HYOPS_ENV") or "").strip()

        if env_name:
            allow_non_shared_env = as_bool(next_inputs.get("allow_non_shared_env"), default=False)
            if (
                env_name.lower() != "shared"
                and normalized_command in ("apply", "deploy", "plan", "validate", "preflight")
                and not allow_non_shared_env
            ):
                return (
                    next_inputs,
                    warnings,
                    "core/onprem/network-sdn is shared-foundation only by default; "
                    f"refusing {normalized_command} in env={env_name}. "
                    "Deploy SDN in --env shared and let other envs consume the shared network/NetBox authority, "
                    "or explicitly set inputs.allow_non_shared_env=true when isolation is intentional.",
                )
            if allow_non_shared_env and env_name.lower() != "shared":
                warnings.append(
                    f"allow_non_shared_env=true: proceeding with non-shared SDN deploy in env={env_name}"
                )
            naming = profile_policy.get("naming") if isinstance(profile_policy, dict) else {}
            naming = naming if isinstance(naming, dict) else {}
            env_code, env_code_err = resolve_env_code(env_name, naming_policy=naming)
            if env_code_err:
                return next_inputs, warnings, env_code_err

            max_len = 8
            raw_proxmox_policy = naming.get("proxmox")
            proxmox_policy: dict[str, Any] = raw_proxmox_policy if isinstance(raw_proxmox_policy, dict) else {}
            try:
                max_len = int(proxmox_policy.get("sdn_id_max_len") or max_len)
            except Exception:
                max_len = 8

            effective, effective_err = compose_compact_id(
                env_code=env_code,
                base=base_zone_name,
                max_len=max_len,
                allowed_re=_PROXMOX_SDN_ID_RE,
            )
            if effective_err:
                return next_inputs, warnings, effective_err

            zone_name = effective
            next_inputs["zone_name"] = zone_name
            warnings.append(
                "naming: env="
                f"{env_name} base_zone_name={base_zone_name} zone_name={zone_name} label={compose_label(env_code=env_code, base=base_zone_name)}"
            )
        # Contract-only input; not part of Terraform stack inputs.
        if "allow_non_shared_env" in next_inputs:
            next_inputs.pop("allow_non_shared_env", None)
        proxmox_tfvars_env = str(
            credential_env.get("HYOPS_PROXMOX_TFVARS")
            or env.get("HYOPS_PROXMOX_TFVARS")
            or ""
        ).strip()
        if not proxmox_tfvars_env:
            return next_inputs, warnings, "missing HYOPS_PROXMOX_TFVARS for SDN zone conflict checks"

        proxmox_tfvars_path = Path(proxmox_tfvars_env).expanduser().resolve()
        proxmox_tfvars = parse_tfvars(proxmox_tfvars_path)
        zone_exists, zone_error = _proxmox_zone_exists(tfvars=proxmox_tfvars, zone_name=zone_name)
        if zone_error:
            return next_inputs, warnings, zone_error

        state_dir_raw = ""
        if isinstance(runtime, dict):
            state_dir_raw = str(runtime.get("state_dir") or "").strip()
        if not state_dir_raw:
            return next_inputs, warnings, "runtime.state_dir is required for SDN ownership checks"

        owned_zone_name, owned_zone_error = _owned_network_sdn_zone_name(
            state_dir=state_dir_raw,
            module_ref=module_ref,
        )
        if owned_zone_error:
            return next_inputs, warnings, owned_zone_error
        if zone_exists:
            if owned_zone_name and owned_zone_name == zone_name:
                operation = "apply/update" if command_name == "apply" else command_name
                warnings.append(
                    f"inputs.zone_name '{zone_name}' already exists and is owned by this module state; proceeding with {operation}"
                )
            else:
                owner_hint = (
                    f"state currently owns zone '{owned_zone_name}'"
                    if owned_zone_name
                    else "no owned zone found in module state"
                )
                return next_inputs, warnings, (
                    f"inputs.zone_name '{zone_name}' already exists in Proxmox SDN and is not owned by this module; "
                    f"choose a new zone_name or remove/import the existing zone ({owner_hint})"
                )

        return next_inputs, warnings, ""

    def validate_push_to_netbox(
        self,
        *,
        command_name: str,
        module_ref: str,
        runtime: dict[str, Any],
    ) -> str:
        state_dir_raw = ""
        if isinstance(runtime, dict):
            state_dir_raw = str(runtime.get("state_dir") or "").strip()
        if not state_dir_raw:
            if command_name == "preflight":
                return "push_to_netbox preflight failed: runtime.state_dir is required"
            return "push_to_netbox requires runtime.state_dir"

        ok, err = _netbox_state_ready(state_dir=state_dir_raw)
        if ok:
            return ""
        return err
