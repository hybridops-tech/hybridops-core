"""Terragrunt driver preflight helpers (internal)."""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

from hyops.runtime.coerce import as_int
from hyops.runtime.terraform_cloud import preflight_cloud_backend

from .netbox import hydrate_netbox_env, netbox_state_status


def run_preflight_phase(
    *,
    command_name: str,
    result: dict[str, Any],
    policy_defaults: dict[str, Any],
    runtime_root: Path,
    backend_mode: str,
    env: dict[str, str],
    env_name: str,
    export_infra_hook: dict[str, Any] | None,
    contract: Any,
    module_ref: str,
    runtime: dict[str, Any],
    profile_ref: str,
    pack_id: str,
    required_credentials: list[str],
    inputs: dict[str, Any],
) -> tuple[bool, str]:
    """Execute preflight-only checks.

    Returns (handled, error_message). When handled and no error, caller should
    write result json and return success immediately.
    """
    if command_name != "preflight":
        return False, ""

    # Guard against late failures during terraform init/provider installs.
    min_free_disk_mb = max(0, int(as_int(policy_defaults.get("min_free_disk_mb"), default=256)))
    if min_free_disk_mb:
        try:
            free_mb = int(shutil.disk_usage(str(runtime_root)).free // (1024 * 1024))
        except Exception:
            free_mb = -1
        if free_mb >= 0 and free_mb < min_free_disk_mb:
            return True, (
                f"insufficient disk space under runtime root: free={free_mb}MB "
                f"required>={min_free_disk_mb}MB ({runtime_root})"
            )

    if backend_mode == "cloud":
        tfc_error = preflight_cloud_backend(env=env, runtime_root=runtime_root, env_name=env_name)
        if tfc_error:
            return True, tfc_error

    if export_infra_hook and bool(export_infra_hook.get("push_to_netbox")):
        strict_netbox = bool(export_infra_hook.get("strict"))

        contract_error = contract.validate_push_to_netbox(
            command_name=command_name,
            module_ref=module_ref,
            runtime=runtime if isinstance(runtime, dict) else {},
        )
        if contract_error:
            if strict_netbox:
                return True, contract_error
            result["warnings"].append(f"push_to_netbox disabled (non-strict): {contract_error}")

        hydrate_warnings, missing = hydrate_netbox_env(env, runtime_root)
        if hydrate_warnings:
            result["warnings"].extend(hydrate_warnings)

        if missing:
            missing_str = ", ".join(missing)
            nb_state = netbox_state_status(runtime_root)
            hint = f"push_to_netbox preflight failed: missing required env vars: {missing_str}. "
            hint += "Provide them via shell env, credentials/netbox.env under the runtime root, or the runtime vault. "
            if "NETBOX_API_TOKEN" in missing:
                vault_file = (runtime_root / "vault" / "bootstrap.vault.env").resolve()
                env_hint = env_name or "<env>"
                hint += f"Generate a token value (length<=40) via: hyops secrets ensure --env {env_hint} NETBOX_API_TOKEN. "
                hint += f"(vault: {vault_file}) "
            if "NETBOX_API_URL" in missing and nb_state and nb_state not in ("ok", "ready"):
                hint += f"NetBox module state platform/onprem/netbox is not ready (status={nb_state}); apply it to publish netbox_api_url. "
            if strict_netbox:
                return True, hint.strip()
            result["warnings"].append(
                f"push_to_netbox disabled (non-strict): missing env vars: {missing_str}"
            )

    result["status"] = "ok"
    result["normalized_outputs"] = {
        "preflight": {
            "module_ref": module_ref,
            "profile_ref": profile_ref,
            "pack_id": pack_id,
            "required_credentials": required_credentials,
            "effective_zone_name": str(inputs.get("zone_name") or ""),
        }
    }
    return True, ""
