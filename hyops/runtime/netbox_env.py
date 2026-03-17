"""NetBox env hydration helpers.

purpose: Provide shared NETBOX_* env hydration from runtime state/vault.
Architecture Decision: ADR-N/A (netbox env hydration)
maintainer: HybridOps.Tech
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any

from hyops.runtime.vault import VaultAuth, read_env


_NETBOX_MODULE_REF = "platform/onprem/netbox"
_AUTHORITY_ROOT_ENV = "HYOPS_NETBOX_AUTHORITY_ROOT"
_AUTHORITY_ENV_ENV = "HYOPS_NETBOX_AUTHORITY_ENV"
_DEFAULT_AUTHORITY_ENV = "shared"

_ENV_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_-]{0,63}$")


def _validate_env_name(env_name: str) -> str:
    env_name = (env_name or "").strip()
    if not env_name:
        raise ValueError("netbox authority env name is empty")
    if "/" in env_name or "\\" in env_name or ".." in env_name:
        raise ValueError(f"invalid netbox authority env name: {env_name!r}")
    if not _ENV_RE.match(env_name):
        raise ValueError(f"invalid netbox authority env name: {env_name!r}")
    return env_name


def resolve_netbox_authority_root(
    env: dict[str, str],
    runtime_root: Path,
) -> tuple[Path | None, str]:
    """Resolve the runtime root that should be treated as NetBox authority.

    This enables a "shared NetBox" pattern where one env publishes NetBox
    credentials/state, while other envs consume it.

    Resolution order:
    1) HYOPS_NETBOX_AUTHORITY_ROOT (path; relative paths are resolved against runtime_root)
    2) HYOPS_NETBOX_AUTHORITY_ENV  (env name under ~/.hybridops/envs/<env>)
    3) Default: shared env (~/.hybridops/envs/shared)

    Returns (authority_root_or_none, error_message).
    """
    raw_root = str(env.get(_AUTHORITY_ROOT_ENV) or "").strip()
    if raw_root:
        p = Path(raw_root).expanduser()
        root = p if p.is_absolute() else (runtime_root / p).resolve()
        return root.resolve(), ""

    raw_env = str(env.get(_AUTHORITY_ENV_ENV) or "").strip()
    if raw_env:
        try:
            name = _validate_env_name(raw_env)
        except Exception as exc:
            return None, str(exc)
        return (Path.home() / ".hybridops" / "envs" / name).resolve(), ""

    # Default (central SSOT): if a shared env exists, prefer it as the NetBox authority.
    # This keeps per-env NetBox possible via HYOPS_NETBOX_AUTHORITY_ENV overrides.
    shared_root = (Path.home() / ".hybridops" / "envs" / _DEFAULT_AUTHORITY_ENV).resolve()
    return shared_root, ""


def normalize_netbox_api_url(raw: str) -> str:
    """Normalize NETBOX_API_URL to the NetBox base URL.

    Accepts both:
    - http(s)://host:port
    - http(s)://host:port/api  (or /api/)
    """
    v = str(raw or "").strip()
    if not v:
        return ""
    v = v.rstrip("/")
    if v.endswith("/api"):
        v = v[:-4]
    return v


def _load_env_file_into_env(env: dict[str, str], path: Path) -> None:
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
        if len(v) >= 2 and ((v[0] == v[-1] == '"') or (v[0] == v[-1] == "'")):
            v = v[1:-1]
        env.setdefault(k, v)


def _read_state_json(runtime_root: Path, module_id: str) -> dict[str, Any]:
    path = (runtime_root / "state" / "modules" / module_id / "latest.json").resolve()
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8")) or {}
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def netbox_state_status(runtime_root: Path) -> str:
    payload = _read_state_json(runtime_root, "platform__onprem__netbox")
    return str(payload.get("status") or "").strip().lower()


def infer_netbox_api_url_from_state(runtime_root: Path) -> str:
    """Infer NETBOX_API_URL from NetBox module state outputs."""
    payload = _read_state_json(runtime_root, "platform__onprem__netbox")
    status = str(payload.get("status") or "").strip().lower()
    if status not in ("ok", "ready"):
        return ""

    outputs = payload.get("outputs")
    if not isinstance(outputs, dict):
        return ""

    raw = str(outputs.get("netbox_api_url") or "").strip()
    if raw:
        return normalize_netbox_api_url(raw)

    raw = str(outputs.get("netbox_url") or "").strip()
    if not raw:
        return ""
    return normalize_netbox_api_url(raw.rstrip("/") + "/api/")


def read_netbox_api_token_from_vault(runtime_root: Path) -> tuple[str, str]:
    """Return (token, error). Error is empty on success or when no vault is present."""
    vault_file = (runtime_root / "vault" / "bootstrap.vault.env").resolve()
    if not vault_file.exists():
        return "", ""
    # NetBox sync hooks are non-strict by default and should not hang for long on a
    # locked GPG session. Use a short bounded timeout just for this vault read path.
    timeout_env = "HYOPS_VAULT_PASSWORD_COMMAND_TIMEOUT_S"
    prev_timeout = os.environ.get(timeout_env)
    timeout_raw = str(os.environ.get("HYOPS_NETBOX_VAULT_READ_TIMEOUT_S") or "").strip()
    timeout_value = "6"
    if timeout_raw:
        try:
            n = int(timeout_raw)
            if n < 2:
                n = 2
            if n > 30:
                n = 30
            timeout_value = str(n)
        except ValueError:
            timeout_value = "6"
    try:
        os.environ[timeout_env] = timeout_value
        env = read_env(vault_file, VaultAuth())
    except Exception as exc:
        msg = str(exc or "").strip()
        low = msg.lower()
        if (
            "timed out" in low
            or "cannot decrypt" in low
            or "decryption failed" in low
            or "public key decryption failed" in low
            or "unlock gpg" in low
            or "pinentry" in low
        ):
            return (
                "",
                "runtime vault unavailable for NETBOX_API_TOKEN (vault locked or GPG not unlocked); "
                "run: hyops vault password >/dev/null",
            )
        return "", f"failed to load runtime vault env: {msg or exc}"
    finally:
        if prev_timeout is None:
            os.environ.pop(timeout_env, None)
        else:
            os.environ[timeout_env] = prev_timeout
    token = str(env.get("NETBOX_API_TOKEN") or "").strip()
    return token, ""


def hydrate_netbox_env(env: dict[str, str], runtime_root: Path) -> tuple[list[str], list[str]]:
    """Try to populate NETBOX_API_URL/NETBOX_API_TOKEN for NetBox workflows.

    Returns (warnings, missing_keys).
    """
    warnings: list[str] = []
    # Preserve explicit operator-provided values from process env.
    explicit_url = str(env.get("NETBOX_API_URL") or "").strip()
    explicit_token = str(env.get("NETBOX_API_TOKEN") or "").strip()

    # 1) Optional operator-provided env file (per-env override).
    _load_env_file_into_env(env, (runtime_root / "credentials" / "netbox.env").resolve())

    # 2) Infer API URL from NetBox module state in the current env (when available).
    if not str(env.get("NETBOX_API_URL") or "").strip():
        inferred = infer_netbox_api_url_from_state(runtime_root)
        if inferred:
            env.setdefault("NETBOX_API_URL", inferred)

    # 3) Load token from runtime vault (preferred; avoids plaintext env file).
    if not str(env.get("NETBOX_API_TOKEN") or "").strip():
        token, err = read_netbox_api_token_from_vault(runtime_root)
        if err:
            warnings.append(err)
        if token:
            env.setdefault("NETBOX_API_TOKEN", token)

    # 4) Optional: NetBox authority env/root (shared NetBox pattern).
    # We only hydrate missing values so a local env can override authority.
    authority_root, authority_err = resolve_netbox_authority_root(env, runtime_root)
    if authority_err:
        warnings.append(authority_err)
        authority_root = None

    if authority_root and authority_root.resolve() != runtime_root.resolve():
        env_file_auth: dict[str, str] = {}
        env_path_auth = (authority_root / "credentials" / "netbox.env").resolve()
        if env_path_auth.is_file():
            try:
                for raw in env_path_auth.read_text(encoding="utf-8").splitlines():
                    line = str(raw or "").strip()
                    if not line or line.startswith("#") or "=" not in line:
                        continue
                    k, v = line.split("=", 1)
                    k = k.strip()
                    v = v.strip()
                    if len(v) >= 2 and ((v[0] == v[-1] == '"') or (v[0] == v[-1] == "'")):
                        v = v[1:-1]
                    if k:
                        env_file_auth[k] = v
            except Exception:
                env_file_auth = {}

        inferred_auth = infer_netbox_api_url_from_state(authority_root)
        token_auth, err_auth = read_netbox_api_token_from_vault(authority_root)
        if err_auth:
            warnings.append(err_auth)

        # Central-authority precedence:
        # If operator didn't explicitly export NETBOX_* in process env, prefer
        # authority values over locally inferred/vault values.
        if not explicit_url:
            auth_url = str(env_file_auth.get("NETBOX_API_URL") or inferred_auth or "").strip()
            if auth_url:
                env["NETBOX_API_URL"] = auth_url

        if not explicit_token:
            auth_token = str(env_file_auth.get("NETBOX_API_TOKEN") or token_auth or "").strip()
            if auth_token:
                env["NETBOX_API_TOKEN"] = auth_token

    # 5) Normalize URL for downstream tooling.
    if str(env.get("NETBOX_API_URL") or "").strip():
        env["NETBOX_API_URL"] = normalize_netbox_api_url(str(env.get("NETBOX_API_URL") or ""))

    missing: list[str] = []
    if not str(env.get("NETBOX_API_URL") or "").strip():
        missing.append("NETBOX_API_URL")
    if not str(env.get("NETBOX_API_TOKEN") or "").strip():
        missing.append("NETBOX_API_TOKEN")

    return warnings, missing


__all__ = [
    "normalize_netbox_api_url",
    "netbox_state_status",
    "infer_netbox_api_url_from_state",
    "read_netbox_api_token_from_vault",
    "resolve_netbox_authority_root",
    "hydrate_netbox_env",
]
