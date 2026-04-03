"""HashiCorp Vault helpers.

purpose: Centralize external HashiCorp Vault API access for validation and secret sync.
maintainer: HybridOps.Tech
"""

from __future__ import annotations

import json
from typing import Mapping
from urllib import error as urllib_error
from urllib import request as urllib_request


def api_request(
    *,
    vault_addr: str,
    token: str,
    method: str,
    api_path: str,
    namespace: str = "",
    payload: Mapping[str, object] | None = None,
) -> dict:
    addr = str(vault_addr or "").strip().rstrip("/")
    path = str(api_path or "").strip().lstrip("/")
    if not addr:
        raise ValueError("vault_addr is empty")
    if not path:
        raise ValueError("api_path is empty")
    if not token:
        raise ValueError("vault token is empty")

    data = None
    headers = {"X-Vault-Token": token}
    if namespace:
        headers["X-Vault-Namespace"] = namespace
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"

    req = urllib_request.Request(
        f"{addr}/v1/{path}",
        data=data,
        method=method.upper(),
        headers=headers,
    )
    try:
        with urllib_request.urlopen(req, timeout=20) as resp:
            raw = resp.read().decode("utf-8")
    except urllib_error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace").strip()
        raise RuntimeError(detail or f"Vault API returned HTTP {exc.code}") from exc
    except urllib_error.URLError as exc:
        raise RuntimeError(f"failed to reach Vault API: {exc.reason}") from exc
    except Exception as exc:
        raise RuntimeError(f"failed to read Vault API response: {exc}") from exc

    if not raw.strip():
        return {}
    try:
        return json.loads(raw)
    except Exception as exc:
        raise RuntimeError(f"Vault API returned non-JSON payload: {exc}") from exc


def lookup_self(*, vault_addr: str, token: str, namespace: str = "") -> dict:
    return api_request(
        vault_addr=vault_addr,
        token=token,
        namespace=namespace,
        method="GET",
        api_path="auth/token/lookup-self",
    )


def resolve_secret_ref(secret_ref: str, *, engine: str) -> tuple[str, str]:
    ref = str(secret_ref or "").strip().lstrip("/")
    field = ""
    if "#" in ref:
        ref, field = ref.rsplit("#", 1)
        ref = ref.strip()
        field = field.strip()
    if ref.startswith("v1/"):
        ref = ref[3:]
    if not ref:
        raise ValueError("secret ref path is empty")
    if engine == "kv-v2" and "/data/" not in ref:
        if "/" not in ref:
            raise ValueError(
                "kv-v2 secret ref must include mount/path, for example 'secret/app/dev#PASSWORD'"
            )
        mount, rest = ref.split("/", 1)
        ref = f"{mount}/data/{rest}"
    return ref, field


def read_secret_data(
    *,
    vault_addr: str,
    token: str,
    secret_ref: str,
    engine: str,
    namespace: str = "",
) -> dict[str, object]:
    api_path, _field = resolve_secret_ref(secret_ref, engine=engine)
    payload = api_request(
        vault_addr=vault_addr,
        token=token,
        namespace=namespace,
        method="GET",
        api_path=api_path,
    )
    data = payload.get("data")
    if isinstance(data, dict) and isinstance(data.get("data"), dict):
        data = data.get("data")
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise RuntimeError("Vault secret response did not contain a readable data object")
    return dict(data)


def fetch_secret_value(
    *,
    vault_addr: str,
    token: str,
    secret_ref: str,
    env_key: str,
    engine: str,
    namespace: str = "",
) -> str:
    api_path, field = resolve_secret_ref(secret_ref, engine=engine)
    field = field or str(env_key or "").strip()
    if not field:
        raise ValueError("vault secret field is empty and env_key is empty")
    payload = api_request(
        vault_addr=vault_addr,
        token=token,
        namespace=namespace,
        method="GET",
        api_path=api_path,
    )
    data = payload.get("data")
    if isinstance(data, dict) and isinstance(data.get("data"), dict):
        data = data.get("data")
    if not isinstance(data, dict):
        raise RuntimeError("Vault secret response did not contain a readable data object")

    value = str(data.get(field) or "").strip()
    if not value:
        raise RuntimeError(f"field '{field}' missing or empty in Vault secret '{secret_ref}'")
    return value


def write_secret_data(
    *,
    vault_addr: str,
    token: str,
    secret_ref: str,
    data: Mapping[str, object],
    engine: str,
    namespace: str = "",
) -> None:
    api_path, _field = resolve_secret_ref(secret_ref, engine=engine)
    if engine == "kv-v2":
        payload: Mapping[str, object] = {"data": dict(data)}
    else:
        payload = dict(data)
    api_request(
        vault_addr=vault_addr,
        token=token,
        namespace=namespace,
        method="POST",
        api_path=api_path,
        payload=payload,
    )


__all__ = [
    "api_request",
    "lookup_self",
    "resolve_secret_ref",
    "read_secret_data",
    "fetch_secret_value",
    "write_secret_data",
]
