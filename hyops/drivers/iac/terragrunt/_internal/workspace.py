"""Terragrunt driver workspace policy helpers (internal)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from hyops.drivers.iac.terraform_cloud.workspace import ensure_workspace_execution_mode
from hyops.runtime.coerce import as_bool
from hyops.runtime.terraform_cloud import derive_workspace_name


def resolve_workspace_policy(
    *,
    profile: dict[str, Any],
    env: dict[str, str],
    module_ref: str,
    pack_id: str,
    inputs: dict[str, Any],
    naming_policy: dict[str, Any] | None,
) -> tuple[dict[str, Any] | None, str]:
    raw = profile.get("workspace_policy")
    if raw is None:
        return None, ""

    if not isinstance(raw, dict):
        return None, "profile.workspace_policy must be a mapping"

    enabled = as_bool(raw.get("enabled"), default=False)
    if not enabled:
        return None, ""

    provider = str(raw.get("provider") or "").strip().lower()
    if not provider:
        return None, "profile.workspace_policy.provider is required when enabled"

    mode = str(raw.get("mode") or "local").strip().lower()
    if mode not in ("local", "remote", "agent"):
        return None, "profile.workspace_policy.mode must be one of: local, remote, agent"

    host_env = str(raw.get("host_env") or "TFC_HOST").strip() or "TFC_HOST"
    org_env = str(raw.get("org_env") or "TFC_ORG").strip() or "TFC_ORG"
    cred_env = str(raw.get("credentials_file_env") or "TFC_CREDENTIALS_FILE").strip() or "TFC_CREDENTIALS_FILE"

    host = str(env.get(host_env) or "app.terraform.io").strip() or "app.terraform.io"
    org = str(env.get(org_env) or "").strip()
    credentials_file_raw = str(env.get(cred_env) or "~/.terraform.d/credentials.tfrc.json").strip()
    credentials_file = str(Path(credentials_file_raw or "~/.terraform.d/credentials.tfrc.json").expanduser().resolve())

    naming = naming_policy if isinstance(naming_policy, dict) else {}
    workspace_name, ws_err = derive_workspace_name(
        provider=provider,
        module_ref=module_ref,
        pack_id=pack_id,
        inputs=inputs,
        env=env,
        env_name=str(env.get("HYOPS_ENV") or "").strip(),
        naming_policy=naming,
    )
    if ws_err:
        return None, ws_err

    return (
        {
            "enabled": True,
            "strict": as_bool(raw.get("strict"), default=False),
            "provider": provider,
            "mode": mode,
            "host": host,
            "org": org,
            "credentials_file": credentials_file,
            "description": str(raw.get("description") or "").strip(),
            "workspace_name": workspace_name,
        },
        "",
    )


def enforce_workspace_policy(
    *,
    backend_mode: str,
    workspace_policy: dict[str, Any] | None,
) -> tuple[dict[str, Any], str, str]:
    """Enforce cloud workspace execution mode policy.

    Returns: (workspace_result, error_message, warning_message)
    """
    if backend_mode != "cloud" or not workspace_policy:
        return {}, "", ""

    workspace_result = ensure_workspace_execution_mode(
        host=str(workspace_policy.get("host") or ""),
        org=str(workspace_policy.get("org") or ""),
        workspace_name=str(workspace_policy.get("workspace_name") or ""),
        execution_mode=str(workspace_policy.get("mode") or ""),
        credentials_file=Path(str(workspace_policy.get("credentials_file") or "~/.terraform.d/credentials.tfrc.json")),
        description=str(workspace_policy.get("description") or "") or None,
    )

    if bool(workspace_result.get("ok")):
        return workspace_result, "", ""

    ws_msg = str(workspace_result.get("message") or "workspace policy enforcement failed")
    ws_status = str(workspace_result.get("status") or "workspace_policy_error")
    if bool(workspace_policy.get("strict")):
        return workspace_result, f"workspace policy failed ({ws_status}): {ws_msg}", ""

    return workspace_result, "", f"workspace policy non-fatal ({ws_status}): {ws_msg}"
