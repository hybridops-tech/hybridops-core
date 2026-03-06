"""Terraform Cloud workspace policy helpers.

purpose: Read Terraform Cloud credentials and enforce workspace execution policy via API.
Architecture Decision: ADR-N/A (workspace policy)
maintainer: HybridOps.Studio
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping
from urllib.error import HTTPError
from urllib.parse import quote
from urllib.request import Request, urlopen
import json

from hyops.runtime.terraform_cloud import require_tfrc_token, tf_token_env_key


_ALLOWED_EXECUTION_MODES = frozenset({"local", "remote", "agent"})


def default_workspace_description(mode: str) -> str:
    m = (mode or "").strip().lower()
    if m == "local":
        return (
            "Local execution. Plans and applies run on the operator workstation. "
            "Terraform Cloud stores state only."
        )
    if m == "remote":
        return "Remote execution. Plans and applies run on Terraform Cloud infrastructure."
    if m == "agent":
        return "Agent execution. Plans and applies run on Terraform Cloud agent pools."
    return "Managed by HybridOps.Core Terragrunt driver."


def read_tfc_token(host: str, credentials_file: Path, env: Mapping[str, str] | None = None) -> str:
    token_key = tf_token_env_key(host)
    if isinstance(env, Mapping):
        token = str(env.get(token_key) or "").strip()
        if token:
            return token
    return require_tfrc_token(host, credentials_file)


def _http_json(
    method: str,
    url: str,
    token: str,
    payload: dict[str, Any] | None = None,
    *,
    timeout_s: int = 20,
) -> tuple[int, dict[str, Any], str]:
    data: bytes | None = None
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")

    req = Request(
        url=url,
        data=data,
        method=method,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/vnd.api+json",
            "Accept": "application/vnd.api+json",
            "User-Agent": "hyops-core/terragrunt-driver",
        },
    )

    try:
        with urlopen(req, timeout=timeout_s) as resp:
            status = int(resp.getcode() or 0)
            raw = resp.read().decode("utf-8", errors="replace")
    except HTTPError as e:
        status = int(e.code or 0)
        try:
            raw_bytes = e.read()
        except Exception:
            raw_bytes = b""
        raw = raw_bytes.decode("utf-8", errors="replace")
    except Exception as e:
        return 0, {}, str(e)

    try:
        parsed = json.loads(raw) if raw.strip() else {}
    except Exception:
        parsed = {}

    if not isinstance(parsed, dict):
        parsed = {}

    return status, parsed, ""


def ensure_workspace_execution_mode(
    *,
    host: str,
    org: str,
    workspace_name: str,
    execution_mode: str,
    credentials_file: Path,
    env: Mapping[str, str] | None = None,
    description: str | None = None,
) -> dict[str, Any]:
    mode = (execution_mode or "").strip().lower()
    if mode not in _ALLOWED_EXECUTION_MODES:
        return {
            "ok": False,
            "status": "invalid_config",
            "message": f"invalid execution mode: {execution_mode}",
            "host": host,
            "org": org,
            "workspace_name": workspace_name,
            "execution_mode": mode,
            "credentials_file": str(credentials_file),
        }

    host_name = (host or "").strip() or "app.terraform.io"
    org_name = (org or "").strip()
    ws_name = (workspace_name or "").strip()
    desc = (description or "").strip() or default_workspace_description(mode)

    if not org_name:
        return {
            "ok": False,
            "status": "invalid_config",
            "message": "terraform cloud org is required",
            "host": host_name,
            "org": org_name,
            "workspace_name": ws_name,
            "execution_mode": mode,
            "credentials_file": str(credentials_file),
        }

    if not ws_name:
        return {
            "ok": False,
            "status": "invalid_config",
            "message": "workspace name is required",
            "host": host_name,
            "org": org_name,
            "workspace_name": ws_name,
            "execution_mode": mode,
            "credentials_file": str(credentials_file),
        }

    try:
        token = read_tfc_token(host_name, credentials_file, env=env)
    except Exception as e:
        return {
            "ok": False,
            "status": "token_missing",
            "message": str(e),
            "host": host_name,
            "org": org_name,
            "workspace_name": ws_name,
            "execution_mode": mode,
            "credentials_file": str(credentials_file),
        }

    org_q = quote(org_name, safe="")
    ws_q = quote(ws_name, safe="")

    get_url = f"https://{host_name}/api/v2/organizations/{org_q}/workspaces/{ws_q}"
    status, body, err = _http_json("GET", get_url, token)
    if err:
        return {
            "ok": False,
            "status": "api_error",
            "message": f"workspace lookup failed: {err}",
            "host": host_name,
            "org": org_name,
            "workspace_name": ws_name,
            "execution_mode": mode,
            "http_status": status,
            "credentials_file": str(credentials_file),
        }

    if status == 404:
        create_url = f"https://{host_name}/api/v2/organizations/{org_q}/workspaces"
        create_payload = {
            "data": {
                "type": "workspaces",
                "attributes": {
                    "name": ws_name,
                    "execution-mode": mode,
                    "description": desc,
                },
            }
        }
        create_status, create_body, create_err = _http_json("POST", create_url, token, create_payload)
        if create_err:
            return {
                "ok": False,
                "status": "workspace_create_error",
                "message": f"workspace create failed: {create_err}",
                "host": host_name,
                "org": org_name,
                "workspace_name": ws_name,
                "execution_mode": mode,
                "http_status": create_status,
                "credentials_file": str(credentials_file),
            }

        create_data = create_body.get("data")
        if create_status not in (200, 201) or not isinstance(create_data, dict):
            return {
                "ok": False,
                "status": "workspace_create_error",
                "message": f"workspace create returned HTTP {create_status}",
                "host": host_name,
                "org": org_name,
                "workspace_name": ws_name,
                "execution_mode": mode,
                "http_status": create_status,
                "credentials_file": str(credentials_file),
            }

        workspace_id = str(create_data.get("id") or "").strip()
        create_attrs = create_data.get("attributes")
        created_mode = (
            str(create_attrs.get("execution-mode") or "").strip().lower()
            if isinstance(create_attrs, dict)
            else ""
        )
        return {
            "ok": True,
            "status": "created",
            "message": "workspace created with requested execution mode",
            "host": host_name,
            "org": org_name,
            "workspace_name": ws_name,
            "workspace_id": workspace_id,
            "execution_mode": mode,
            "current_mode": created_mode,
            "http_status": create_status,
            "credentials_file": str(credentials_file),
        }

    if status != 200:
        return {
            "ok": False,
            "status": "api_error",
            "message": f"workspace lookup returned HTTP {status}",
            "host": host_name,
            "org": org_name,
            "workspace_name": ws_name,
            "execution_mode": mode,
            "http_status": status,
            "credentials_file": str(credentials_file),
        }

    data = body.get("data")
    if not isinstance(data, dict):
        return {
            "ok": False,
            "status": "api_error",
            "message": "workspace lookup returned invalid payload",
            "host": host_name,
            "org": org_name,
            "workspace_name": ws_name,
            "execution_mode": mode,
            "http_status": status,
            "credentials_file": str(credentials_file),
        }

    workspace_id = str(data.get("id") or "").strip()
    raw_attrs = data.get("attributes")
    attrs: dict[str, Any]
    if isinstance(raw_attrs, dict):
        attrs = raw_attrs
    else:
        attrs = {}
    current_mode = str(attrs.get("execution-mode") or "").strip().lower()
    current_desc = str(attrs.get("description") or "").strip()

    if not workspace_id:
        return {
            "ok": False,
            "status": "api_error",
            "message": "workspace lookup returned empty workspace id",
            "host": host_name,
            "org": org_name,
            "workspace_name": ws_name,
            "workspace_id": workspace_id,
            "execution_mode": mode,
            "http_status": status,
            "credentials_file": str(credentials_file),
        }

    needs_update = current_mode != mode or not current_desc
    if not needs_update:
        return {
            "ok": True,
            "status": "unchanged",
            "message": "workspace execution mode already matches policy",
            "host": host_name,
            "org": org_name,
            "workspace_name": ws_name,
            "workspace_id": workspace_id,
            "execution_mode": mode,
            "current_mode": current_mode,
            "http_status": status,
            "credentials_file": str(credentials_file),
        }

    patch_payload = {
        "data": {
            "type": "workspaces",
            "attributes": {
                "execution-mode": mode,
                "description": desc,
            },
        }
    }
    patch_url = f"https://{host_name}/api/v2/workspaces/{quote(workspace_id, safe='')}"
    patch_status, _, patch_err = _http_json("PATCH", patch_url, token, patch_payload)

    if patch_err:
        return {
            "ok": False,
            "status": "api_error",
            "message": f"workspace update failed: {patch_err}",
            "host": host_name,
            "org": org_name,
            "workspace_name": ws_name,
            "workspace_id": workspace_id,
            "execution_mode": mode,
            "current_mode": current_mode,
            "http_status": patch_status,
            "credentials_file": str(credentials_file),
        }

    if patch_status != 200:
        return {
            "ok": False,
            "status": "api_error",
            "message": f"workspace update returned HTTP {patch_status}",
            "host": host_name,
            "org": org_name,
            "workspace_name": ws_name,
            "workspace_id": workspace_id,
            "execution_mode": mode,
            "current_mode": current_mode,
            "http_status": patch_status,
            "credentials_file": str(credentials_file),
        }

    return {
        "ok": True,
        "status": "updated",
        "message": "workspace execution mode updated",
        "host": host_name,
        "org": org_name,
        "workspace_name": ws_name,
        "workspace_id": workspace_id,
        "execution_mode": mode,
        "current_mode": current_mode,
        "http_status": patch_status,
        "credentials_file": str(credentials_file),
    }


def ensure_workspace(
    *,
    host: str,
    org: str,
    workspace_name: str,
    execution_mode: str,
    credentials_file: Path,
    description: str | None = None,
) -> dict[str, Any]:
    """Ensure a Terraform Cloud workspace exists (create if missing).

    This is intended for operator-facing bootstrap/ops flows where the workspace
    should be created explicitly (headless, no GUI dependency) and then kept at
    the requested execution mode.
    """

    mode = (execution_mode or "").strip().lower()
    if mode not in _ALLOWED_EXECUTION_MODES:
        return {
            "ok": False,
            "status": "invalid_config",
            "message": f"invalid execution mode: {execution_mode}",
            "host": host,
            "org": org,
            "workspace_name": workspace_name,
            "execution_mode": mode,
            "credentials_file": str(credentials_file),
        }

    host_name = (host or "").strip() or "app.terraform.io"
    org_name = (org or "").strip()
    ws_name = (workspace_name or "").strip()
    desc = (description or "").strip() or default_workspace_description(mode)

    if not org_name:
        return {
            "ok": False,
            "status": "invalid_config",
            "message": "terraform cloud org is required",
            "host": host_name,
            "org": org_name,
            "workspace_name": ws_name,
            "execution_mode": mode,
            "credentials_file": str(credentials_file),
        }

    if not ws_name:
        return {
            "ok": False,
            "status": "invalid_config",
            "message": "workspace name is required",
            "host": host_name,
            "org": org_name,
            "workspace_name": ws_name,
            "execution_mode": mode,
            "credentials_file": str(credentials_file),
        }

    try:
        token = read_tfc_token(host_name, credentials_file)
    except Exception as e:
        return {
            "ok": False,
            "status": "token_missing",
            "message": str(e),
            "host": host_name,
            "org": org_name,
            "workspace_name": ws_name,
            "execution_mode": mode,
            "credentials_file": str(credentials_file),
        }

    org_q = quote(org_name, safe="")
    ws_q = quote(ws_name, safe="")
    get_url = f"https://{host_name}/api/v2/organizations/{org_q}/workspaces/{ws_q}"
    get_status, get_body, get_err = _http_json("GET", get_url, token)
    if get_err:
        return {
            "ok": False,
            "status": "api_error",
            "message": f"workspace lookup failed: {get_err}",
            "host": host_name,
            "org": org_name,
            "workspace_name": ws_name,
            "execution_mode": mode,
            "http_status": get_status,
            "credentials_file": str(credentials_file),
        }

    if get_status == 404:
        create_url = f"https://{host_name}/api/v2/organizations/{org_q}/workspaces"
        create_payload = {
            "data": {
                "type": "workspaces",
                "attributes": {
                    "name": ws_name,
                    "execution-mode": mode,
                    "description": desc,
                },
            }
        }
        create_status, create_body, create_err = _http_json("POST", create_url, token, create_payload)
        if create_err:
            return {
                "ok": False,
                "status": "api_error",
                "message": f"workspace create failed: {create_err}",
                "host": host_name,
                "org": org_name,
                "workspace_name": ws_name,
                "execution_mode": mode,
                "http_status": create_status,
                "credentials_file": str(credentials_file),
            }

        if create_status not in (200, 201):
            return {
                "ok": False,
                "status": "api_error",
                "message": f"workspace create returned HTTP {create_status}",
                "host": host_name,
                "org": org_name,
                "workspace_name": ws_name,
                "execution_mode": mode,
                "http_status": create_status,
                "credentials_file": str(credentials_file),
            }

        data = create_body.get("data")
        workspace_id = str(data.get("id") or "").strip() if isinstance(data, dict) else ""
        return {
            "ok": True,
            "status": "created",
            "message": "workspace created",
            "host": host_name,
            "org": org_name,
            "workspace_name": ws_name,
            "workspace_id": workspace_id,
            "execution_mode": mode,
            "http_status": create_status,
            "credentials_file": str(credentials_file),
        }

    if get_status != 200:
        return {
            "ok": False,
            "status": "api_error",
            "message": f"workspace lookup returned HTTP {get_status}",
            "host": host_name,
            "org": org_name,
            "workspace_name": ws_name,
            "execution_mode": mode,
            "http_status": get_status,
            "credentials_file": str(credentials_file),
        }

    # Workspace exists: ensure execution mode/description matches policy.
    mode_result = ensure_workspace_execution_mode(
        host=host_name,
        org=org_name,
        workspace_name=ws_name,
        execution_mode=mode,
        credentials_file=credentials_file,
        description=desc,
    )
    if bool(mode_result.get("ok")):
        mode_result.setdefault("workspace_preexisted", True)
    return mode_result
