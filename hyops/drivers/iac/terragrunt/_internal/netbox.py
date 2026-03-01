"""NetBox/env helpers for the Terragrunt driver."""

from __future__ import annotations

import json
from pathlib import Path

from hyops.runtime.vault import VaultAuth, read_env


def load_env_file_into_env(env: dict[str, str], path: Path) -> None:
    """Best-effort load KEY=VALUE pairs into env (setdefault semantics)."""
    if not path.is_file():
        return
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except Exception:
        return

    for raw in lines:
        line = str(raw or "").strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        k = k.strip()
        v = v.strip()
        if not k:
            continue
        # Remove surrounding quotes when present.
        if len(v) >= 2 and ((v[0] == v[-1] == '"') or (v[0] == v[-1] == "'")):
            v = v[1:-1]
        env.setdefault(k, v)


def read_module_state(runtime_root: Path, module_id: str) -> dict[str, object]:
    path = (runtime_root / "state" / "modules" / module_id / "latest.json").resolve()
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8")) or {}
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def netbox_state_status(runtime_root: Path) -> str:
    payload = read_module_state(runtime_root, "platform__onprem__netbox")
    return str(payload.get("status") or "").strip().lower()


def infer_netbox_api_url_from_state(runtime_root: Path) -> str:
    payload = read_module_state(runtime_root, "platform__onprem__netbox")
    status = str(payload.get("status") or "").strip().lower()
    if status not in ("ok", "ready"):
        return ""
    outputs = payload.get("outputs")
    if not isinstance(outputs, dict):
        return ""
    raw = str(outputs.get("netbox_api_url") or "").strip()
    if raw:
        return raw
    raw = str(outputs.get("netbox_url") or "").strip()
    if not raw:
        return ""
    return raw.rstrip("/") + "/api/"


def read_netbox_api_token_from_vault(runtime_root: Path) -> tuple[str, str]:
    """Return (token, error). Error is empty on success or when no vault is present."""
    vault_file = (runtime_root / "vault" / "bootstrap.vault.env").resolve()
    if not vault_file.exists():
        return "", ""
    try:
        env = read_env(vault_file, VaultAuth())
    except Exception as exc:
        return "", f"failed to load runtime vault env: {exc}"
    token = str(env.get("NETBOX_API_TOKEN") or "").strip()
    return token, ""


def hydrate_netbox_env(env: dict[str, str], runtime_root: Path) -> tuple[list[str], list[str]]:
    """Try to populate NETBOX_API_URL/NETBOX_API_TOKEN for NetBox workflows.

    Returns (warnings, missing_keys).
    """
    from hyops.runtime.netbox_env import hydrate_netbox_env as _hydrate_netbox_env

    return _hydrate_netbox_env(env, runtime_root)
