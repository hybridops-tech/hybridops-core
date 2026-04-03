#!/usr/bin/env python3
# purpose: Minimal NetBox API wrapper for idempotent infrastructure import
# adr: ADR-0002_source-of-truth_netbox-driven-inventory
# maintainer: HybridOps.Tech

from __future__ import annotations

import os
import random
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

import requests

from .paths import RUNTIME_ROOT, control_secrets_env_path


class NetBoxConfigError(RuntimeError):
    pass


class NetBoxConflictError(RuntimeError):
    pass


_RETRY_STATUS_CODES = {429, 500, 502, 503, 504}
_MAX_RETRIES = 5
_BACKOFF_BASE_SECONDS = 0.5
_BACKOFF_CAP_SECONDS = 10.0


def _sleep_backoff(attempt: int, *, retry_after_seconds: float | None = None) -> None:
    if retry_after_seconds is not None:
        time.sleep(min(_BACKOFF_CAP_SECONDS, max(0.0, retry_after_seconds)))
        return

    delay = min(_BACKOFF_CAP_SECONDS, _BACKOFF_BASE_SECONDS * (2**attempt))
    delay += random.uniform(0.0, 0.25)
    time.sleep(delay)


def _send(
    client: "NetBoxClient",
    method: str,
    url: str,
    *,
    params: Dict[str, Any] | None = None,
    json_payload: Dict[str, Any] | None = None,
    timeout: int = 30,
) -> requests.Response:
    last_exc: Exception | None = None

    for attempt in range(_MAX_RETRIES):
        try:
            resp = client.session.request(
                method,
                url,
                params=params,
                json=json_payload,
                timeout=timeout,
            )
        except requests.RequestException as exc:  # noqa: PERF203
            last_exc = exc
            if attempt >= _MAX_RETRIES - 1:
                raise
            _sleep_backoff(attempt)
            continue

        if resp.status_code in _RETRY_STATUS_CODES:
            if attempt >= _MAX_RETRIES - 1:
                return resp

            retry_after = resp.headers.get("Retry-After", "").strip()
            if resp.status_code == 429 and retry_after.isdigit():
                _sleep_backoff(attempt, retry_after_seconds=float(retry_after))
            else:
                _sleep_backoff(attempt)
            continue

        return resp

    if last_exc is not None:
        raise last_exc
    raise RuntimeError("NetBox request failed")


def _load_secrets_env_into_os(path: Path) -> None:
    if not path.is_file():
        return

    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue

        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if not key:
            continue

        if value.startswith('"') and value.endswith('"'):
            value = value[1:-1]
            value = value.replace(r"\\", "\\").replace(r"\"", '"')

        os.environ.setdefault(key, value)

def _load_runtime_vault_into_os() -> None:
    """Best-effort load the encrypted runtime vault env into os.environ.

    This keeps NetBox tooling usable without exporting NETBOX_* vars into the shell,
    as long as the operator has bootstrapped vault access.
    """
    vault_file = (RUNTIME_ROOT / "vault" / "bootstrap.vault.env").resolve()
    if not vault_file.exists():
        return
    try:
        from hyops.runtime.vault import VaultAuth, read_env
    except Exception:
        return
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
        data = read_env(vault_file, VaultAuth())
    except Exception:
        return
    finally:
        if prev_timeout is None:
            os.environ.pop(timeout_env, None)
        else:
            os.environ[timeout_env] = prev_timeout
    if not isinstance(data, dict):
        return
    for k, v in data.items():
        if not isinstance(k, str) or not isinstance(v, str):
            continue
        os.environ.setdefault(k, v)


def _require_env(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        _load_secrets_env_into_os(control_secrets_env_path())
        value = os.environ.get(name, "").strip()
    if not value:
        _load_runtime_vault_into_os()
        value = os.environ.get(name, "").strip()
    if not value:
        raise NetBoxConfigError(
            f"{name} must be set in the environment, credentials/netbox.env, or runtime vault (vault/bootstrap.vault.env)"
        )
    return value


def _normalize_base_url(raw: str) -> str:
    v = str(raw or "").strip()
    if not v:
        return ""
    v = v.rstrip("/")
    # Allow NETBOX_API_URL to be set to either the base URL or /api/ endpoint.
    if v.endswith("/api"):
        v = v[:-4]
    return v


@dataclass(frozen=True)
class NetBoxClient:
    base_url: str
    token: str
    session: requests.Session
    dry_run: bool = False


def client_from(*, base_url: str, token: str, dry_run: bool = False) -> NetBoxClient:
    base_url_norm = _normalize_base_url(base_url)
    if not base_url_norm:
        raise NetBoxConfigError("NETBOX_API_URL must be set to a non-empty http(s) base URL")
    token = str(token or "").strip()
    if not token:
        raise NetBoxConfigError("NETBOX_API_TOKEN must be set to a non-empty token")

    session = requests.Session()
    session.headers.update(
        {
            "Authorization": f"Token {token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
    )

    return NetBoxClient(base_url=base_url_norm, token=token, session=session, dry_run=dry_run)


def get_client(*, dry_run: bool = False) -> NetBoxClient:
    base_url = _normalize_base_url(_require_env("NETBOX_API_URL"))
    token = _require_env("NETBOX_API_TOKEN")
    return client_from(base_url=base_url, token=token, dry_run=dry_run)


def probe_client(client: NetBoxClient, *, timeout: int = 5) -> None:
    """Fast API reachability/auth check for operator-facing sync commands.

    Uses a single request (no retry loop) to avoid long apparent hangs before
    the first import row is processed.
    """
    path = f"{client.base_url}/api/status/"
    try:
        resp = client.session.request("GET", path, timeout=timeout)
    except requests.RequestException as exc:
        raise RuntimeError(f"NetBox API unreachable: {exc}") from exc
    if resp.status_code >= 400:
        snippet = (resp.text or "").strip()
        if len(snippet) > 300:
            snippet = snippet[:300] + "..."
        if snippet:
            raise RuntimeError(f"NetBox API probe failed ({resp.status_code}): {snippet}")
        resp.raise_for_status()


def _get_one(client: NetBoxClient, path: str, params: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    url = f"{client.base_url}{path}"
    resp = _send(client, "GET", url, params=params, timeout=30)
    resp.raise_for_status()
    data = resp.json()
    if data.get("count", 0) > 0:
        return data["results"][0]
    return None


def _post(client: NetBoxClient, path: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    if client.dry_run:
        print(f"dry-run: POST {path} payload={payload}")
        return {"id": -1, **payload}

    url = f"{client.base_url}{path}"
    resp = _send(client, "POST", url, json_payload=payload, timeout=30)
    if resp.status_code >= 400:
        snippet = (resp.text or "").strip()
        if len(snippet) > 600:
            snippet = snippet[:600] + "..."
        if snippet:
            raise RuntimeError(f"NetBox POST {path} failed ({resp.status_code}): {snippet}")
        resp.raise_for_status()
    return resp.json()


def _patch(client: NetBoxClient, path: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    if client.dry_run:
        print(f"dry-run: PATCH {path} payload={payload}")
        return {"id": -1, **payload}

    url = f"{client.base_url}{path}"
    resp = _send(client, "PATCH", url, json_payload=payload, timeout=30)
    if resp.status_code >= 400:
        snippet = (resp.text or "").strip()
        if len(snippet) > 600:
            snippet = snippet[:600] + "..."
        if snippet:
            raise RuntimeError(f"NetBox PATCH {path} failed ({resp.status_code}): {snippet}")
        resp.raise_for_status()
    return resp.json()


def _slugify(value: str) -> str:
    text = re.sub(r"[^a-z0-9]+", "-", value.strip().lower()).strip("-")
    return text or "hyops"


def _env_bool(name: str, default: bool) -> bool:
    raw = str(os.environ.get(name, "")).strip().lower()
    if not raw:
        return bool(default)
    if raw in {"1", "true", "yes", "on"}:
        return True
    if raw in {"0", "false", "no", "off"}:
        return False
    return bool(default)


def _is_unknown_custom_field_error(exc: Exception, field_name: str) -> bool:
    msg = str(exc or "")
    field = str(field_name or "").strip()
    if not field:
        return False
    return (
        f"Unknown field name '{field}' in custom field data." in msg
        or ("Unknown field name" in msg and "custom field data" in msg and field in msg)
    )


def _is_unknown_request_field_error(exc: Exception, field_name: str) -> bool:
    msg = str(exc or "")
    field = str(field_name or "").strip()
    if not field:
        return False
    return (
        f"Unknown field name '{field}'" in msg
        or (f"Unknown field '{field}'" in msg)
        or ("unknown field" in msg.lower() and field.lower() in msg.lower())
    )


def ensure_site(client: NetBoxClient, site_slug: str) -> Dict[str, Any]:
    site_slug = site_slug.strip()
    if not site_slug:
        raise NetBoxConfigError("site slug is required")

    path = "/api/dcim/sites/"
    existing = _get_one(client, path, {"slug": site_slug})
    if existing:
        return existing

    payload = {"name": site_slug, "slug": site_slug}
    return _post(client, path, payload)


def ensure_ipam_role(client: NetBoxClient, role_name: str) -> Dict[str, Any]:
    role_name = role_name.strip()
    if not role_name:
        raise NetBoxConfigError("role name is required")

    slug = _slugify(role_name)
    path = "/api/ipam/roles/"
    existing = _get_one(client, path, {"slug": slug})
    if existing:
        return existing

    payload = {"name": role_name, "slug": slug}
    return _post(client, path, payload)


def ensure_vlan(
    client: NetBoxClient,
    *,
    vid: int,
    site_id: int,
    name: str,
    role_id: int | None,
) -> Dict[str, Any]:
    path = "/api/ipam/vlans/"
    existing = _get_one(client, path, {"vid": vid, "site_id": site_id})

    payload: Dict[str, Any] = {"name": name, "site": site_id, "vid": vid}
    if role_id is not None:
        payload["role"] = role_id

    if existing:
        return _patch(client, f"{path}{existing['id']}/", payload)

    return _post(client, path, payload)


def ensure_prefix(
    client: NetBoxClient,
    *,
    prefix: str,
    site_id: int,
    vlan_id: int | None,
    role_id: int | None,
    status: str,
    description: str,
) -> Dict[str, Any]:
    path = "/api/ipam/prefixes/"
    existing = _get_one(client, path, {"prefix": prefix, "site_id": site_id})

    payload: Dict[str, Any] = {
        "prefix": prefix,
        "site": site_id,
        "status": status,
        "description": description,
    }

    if vlan_id is not None:
        payload["vlan"] = vlan_id

    if role_id is not None:
        payload["role"] = role_id

    if existing:
        return _patch(client, f"{path}{existing['id']}/", payload)
    return _post(client, path, payload)

def ensure_ip_range(
    client: NetBoxClient,
    *,
    start_address: str,
    end_address: str,
    role_id: int | None,
    status: str,
    description: str,
) -> Dict[str, Any]:
    path = "/api/ipam/ip-ranges/"
    existing = _get_one(client, path, {"start_address": start_address, "end_address": end_address})

    payload: Dict[str, Any] = {
        "start_address": start_address,
        "end_address": end_address,
        "status": status,
        "description": description,
    }
    if role_id is not None:
        payload["role"] = role_id

    if existing:
        return _patch(client, f"{path}{existing['id']}/", payload)

    return _post(client, path, payload)


def normalize_ip(address_raw: str) -> str | None:
    v = address_raw.strip()
    if not v or v.lower() == "dhcp":
        return None
    if "/" in v:
        return v
    return f"{v}/32"


def ensure_cluster_type(
    client: NetBoxClient,
    *,
    name: str | None = None,
    slug: str | None = None,
) -> Dict[str, Any]:
    path = "/api/virtualization/cluster-types/"
    type_name = (name or os.environ.get("NETBOX_CLUSTER_TYPE_NAME") or "").strip() or "hyops-managed"
    type_slug = (slug or os.environ.get("NETBOX_CLUSTER_TYPE_SLUG") or "").strip() or _slugify(type_name)

    existing = _get_one(client, path, {"slug": type_slug})
    if existing:
        return existing

    existing = _get_one(client, path, {"name": type_name})
    if existing:
        return existing

    payload: Dict[str, Any] = {"name": type_name, "slug": type_slug}
    return _post(client, path, payload)


def ensure_device_role(client: NetBoxClient, role_name: str) -> Dict[str, Any]:
    role_name = str(role_name or "").strip()
    if not role_name:
        raise NetBoxConfigError("device role name is required")

    path = "/api/dcim/device-roles/"
    role_slug = _slugify(role_name)

    existing = _get_one(client, path, {"slug": role_slug})
    if existing:
        return existing

    existing = _get_one(client, path, {"name": role_name})
    if existing:
        return existing

    color = str(os.environ.get("NETBOX_VM_ROLE_COLOR") or "").strip() or "607d8b"
    payload: Dict[str, Any] = {"name": role_name, "slug": role_slug, "color": color}
    return _post(client, path, payload)


def ensure_vm_external_id_custom_field(
    client: NetBoxClient,
    *,
    field_name: str,
) -> Dict[str, Any]:
    field_name = str(field_name or "").strip()
    if not field_name:
        raise NetBoxConfigError("custom field name is required")

    path = "/api/extras/custom-fields/"
    existing = _get_one(client, path, {"name": field_name})
    if existing:
        return existing

    label = str(os.environ.get("NETBOX_VM_EXTERNAL_ID_LABEL") or "").strip() or "External ID"
    description = (
        str(os.environ.get("NETBOX_VM_EXTERNAL_ID_DESCRIPTION") or "").strip()
        or "HybridOps provider linkage for VM reconciliation"
    )
    object_type = str(os.environ.get("NETBOX_VM_EXTERNAL_ID_OBJECT_TYPE") or "").strip() or "virtualization.virtualmachine"

    base_payload: Dict[str, Any] = {
        "name": field_name,
        "label": label,
        "type": "text",
        "required": False,
        "description": description,
    }

    payload = dict(base_payload)
    payload["object_types"] = [object_type]
    try:
        return _post(client, path, payload)
    except Exception as exc:
        if not _is_unknown_request_field_error(exc, "object_types"):
            raise

    # NetBox API compatibility fallback (older/newer variants may use content_types naming)
    payload = dict(base_payload)
    payload["content_types"] = [object_type]
    return _post(client, path, payload)


def ensure_tag(client: NetBoxClient, tag_name: str) -> Dict[str, Any]:
    tag_name = str(tag_name or "").strip()
    if not tag_name:
        raise NetBoxConfigError("tag name is required")

    path = "/api/extras/tags/"
    tag_slug = _slugify(tag_name)

    existing = _get_one(client, path, {"slug": tag_slug})
    if existing:
        return existing

    existing = _get_one(client, path, {"name": tag_name})
    if existing:
        return existing

    color = str(os.environ.get("NETBOX_TAG_COLOR") or "").strip() or "9e9e9e"
    payload: Dict[str, Any] = {"name": tag_name, "slug": tag_slug, "color": color}
    return _post(client, path, payload)


def _resolve_tag_ids(client: NetBoxClient, tags: List[str]) -> List[int]:
    out: list[int] = []
    seen_names: set[str] = set()
    for raw in tags:
        name = str(raw or "").strip()
        if not name:
            continue
        key = name.lower()
        if key in seen_names:
            continue
        seen_names.add(key)
        tag = ensure_tag(client, name)
        out.append(int(tag["id"]))
    return out


def ensure_cluster(client: NetBoxClient, name: str) -> Dict[str, Any]:
    path = "/api/virtualization/clusters/"
    existing = _get_one(client, path, {"name": name})
    if existing:
        return existing

    type_id_raw = os.environ.get("NETBOX_CLUSTER_TYPE_ID", "").strip()
    type_id: int | None = None
    if type_id_raw:
        type_id = int(type_id_raw)
    elif _env_bool("NETBOX_CLUSTER_AUTO_CREATE", default=True):
        cluster_type = ensure_cluster_type(client)
        type_id = int(cluster_type["id"])

    if type_id is None:
        raise NetBoxConfigError(
            "NetBox cluster not found: "
            f"{name}. Create it in NetBox, set NETBOX_CLUSTER_TYPE_ID, or leave "
            "NETBOX_CLUSTER_AUTO_CREATE enabled (default) for HybridOps auto-create."
        )

    payload: Dict[str, Any] = {"name": name, "type": int(type_id)}
    return _post(client, path, payload)


def get_cluster(client: NetBoxClient, name: str) -> Dict[str, Any] | None:
    path = "/api/virtualization/clusters/"
    return _get_one(client, path, {"name": name})


def ensure_vm(
    client: NetBoxClient,
    *,
    name: str,
    cluster_id: int,
    status: str,
    vcpus: int | None = None,
    memory_mb: int | None = None,
    disk_mb: int | None = None,
    role_id: int | None = None,
    tags: List[str] | None = None,
    external_id: str | None = None,
    external_id_field: str = "external_id",
) -> Dict[str, Any]:
    path = "/api/virtualization/virtual-machines/"
    existing: Dict[str, Any] | None = None
    resolved_external_id_field = str(
        os.environ.get("NETBOX_VM_EXTERNAL_ID_FIELD") or external_id_field
    ).strip() or external_id_field
    if external_id:
        for vm in list_vms_in_cluster(client, cluster_id=cluster_id):
            custom_fields = vm.get("custom_fields") or {}
            if str(custom_fields.get(resolved_external_id_field) or "").strip() == external_id:
                existing = vm
                break

    if existing is None:
        params: Dict[str, Any] = {"name": name, "cluster_id": cluster_id}
        existing = _get_one(client, path, params)

    payload: Dict[str, Any] = {
        "name": name,
        "cluster": cluster_id,
        "status": status,
    }
    if vcpus is not None and vcpus >= 0:
        payload["vcpus"] = int(vcpus)
    if memory_mb is not None and memory_mb >= 0:
        payload["memory"] = int(memory_mb)
    if disk_mb is not None and disk_mb >= 0:
        payload["disk"] = int(disk_mb)
    if role_id is not None and role_id > 0:
        payload["role"] = int(role_id)
    if external_id:
        payload["custom_fields"] = {resolved_external_id_field: external_id}
    if tags:
        payload["tags"] = _resolve_tag_ids(client, tags)

    def _without_custom_fields(src: Dict[str, Any]) -> Dict[str, Any]:
        out = dict(src)
        out.pop("custom_fields", None)
        return out

    auto_create_external_id_cf = _env_bool("NETBOX_VM_EXTERNAL_ID_CF_AUTO_CREATE", default=True)

    if existing:
        try:
            return _patch(client, f"{path}{existing['id']}/", payload)
        except Exception as exc:
            if external_id and "custom_fields" in payload and _is_unknown_custom_field_error(exc, resolved_external_id_field):
                if auto_create_external_id_cf:
                    try:
                        ensure_vm_external_id_custom_field(client, field_name=resolved_external_id_field)
                        return _patch(client, f"{path}{existing['id']}/", payload)
                    except Exception:
                        pass
                return _patch(client, f"{path}{existing['id']}/", _without_custom_fields(payload))
            raise

    try:
        return _post(client, path, payload)
    except Exception as exc:
        if external_id and "custom_fields" in payload and _is_unknown_custom_field_error(exc, resolved_external_id_field):
            if auto_create_external_id_cf:
                try:
                    ensure_vm_external_id_custom_field(client, field_name=resolved_external_id_field)
                    return _post(client, path, payload)
                except Exception:
                    pass
            return _post(client, path, _without_custom_fields(payload))
        raise


def ensure_interface(
    client: NetBoxClient,
    *,
    vm_id: int,
    name: str,
    mac_address: str | None = None,
) -> Dict[str, Any]:
    path = "/api/virtualization/interfaces/"
    existing = _get_one(client, path, {"virtual_machine_id": vm_id, "name": name})
    mac_address = str(mac_address or "").strip()
    if existing:
        if mac_address:
            current_mac = str(existing.get("mac_address") or "").strip()
            if current_mac.lower() != mac_address.lower():
                try:
                    existing = _patch(client, f"{path}{existing['id']}/", {"mac_address": mac_address})
                except Exception:
                    # Best-effort MAC sync; keep interface import compatible across NetBox variants.
                    pass
        return existing

    if client.dry_run:
        payload = {"virtual_machine": vm_id, "name": name, "type": "virtual"}
        if mac_address:
            payload["mac_address"] = mac_address
        print(f"dry-run: POST {path} payload={payload}")
        return {"id": -1, **payload}

    url = f"{client.base_url}{path}"
    payload = {"virtual_machine": vm_id, "name": name, "type": "virtual"}
    if mac_address:
        payload["mac_address"] = mac_address
    resp = _send(client, "POST", url, json_payload=payload, timeout=30)

    if resp.status_code == 400 and "type" in (resp.text or ""):
        payload.pop("type", None)
        resp = _send(client, "POST", url, json_payload=payload, timeout=30)

    if resp.status_code == 400 and mac_address and "mac" in (resp.text or "").lower():
        payload.pop("mac_address", None)
        resp = _send(client, "POST", url, json_payload=payload, timeout=30)

    resp.raise_for_status()
    return resp.json()


def ensure_ip(client: NetBoxClient, *, address: str) -> Dict[str, Any]:
    path = "/api/ipam/ip-addresses/"
    existing = _get_one(client, path, {"address": address})
    if existing:
        return existing

    if client.dry_run:
        payload = {"address": address, "status": "active"}
        return _post(client, path, payload)

    # NetBox address filtering can be exact-string sensitive across versions
    # (e.g. prefix length variants). On duplicate POST, fall back to a host-IP
    # search and reuse the existing record instead of failing the sync.
    payload = {"address": address, "status": "active"}
    url = f"{client.base_url}{path}"
    resp = _send(client, "POST", url, json_payload=payload, timeout=30)
    if resp.status_code == 400:
        raw_text = str(resp.text or "")
        text = raw_text.lower()
        if "duplicate" in text or "already exists" in text or "unique" in text:
            host_only = str(address).split("/", 1)[0].strip()
            for params in ({"address": address}, {"address": host_only}, {"q": host_only}):
                found = _get_one(client, path, params)
                if found:
                    found_addr = str(found.get("address") or "")
                    if found_addr.split("/", 1)[0].strip() == host_only:
                        return found
            snippet = raw_text.strip().replace("\n", " ")
            if len(snippet) > 400:
                snippet = snippet[:400] + "..."
            raise RuntimeError(f"duplicate IP exists but could not be looked up for reuse: {address}: {snippet}")
        snippet = raw_text.strip().replace("\n", " ")
        if len(snippet) > 600:
            snippet = snippet[:600] + "..."
        raise RuntimeError(f"NetBox POST {path} failed ({resp.status_code}): {snippet}")
    if resp.status_code >= 400:
        resp.raise_for_status()
    return resp.json()


def find_ip_by_description(client: NetBoxClient, *, description: str) -> Optional[Dict[str, Any]]:
    description = description.strip()
    if not description:
        raise NetBoxConfigError("description is required")
    path = "/api/ipam/ip-addresses/"
    return _get_one(client, path, {"description": description})


def reserve_ip(
    client: NetBoxClient,
    *,
    address: str,
    description: str,
    status: str = "reserved",
    tags: List[str] | None = None,
) -> Dict[str, Any]:
    """Reserve an IP address in NetBox.

    This is intended for "allocate then provision" workflows where HybridOps wants NetBox
    to be the concurrency guard before assigning a static IP on the network.
    """
    if client.dry_run:
        payload: Dict[str, Any] = {"address": address, "status": status, "description": description}
        if tags:
            payload["tags"] = tags
        print(f"dry-run: POST /api/ipam/ip-addresses/ payload={payload}")
        return {"id": -1, **payload}

    path = "/api/ipam/ip-addresses/"
    url = f"{client.base_url}{path}"

    payload: Dict[str, Any] = {
        "address": address,
        "status": status,
        "description": description,
    }
    if tags:
        tag_payload: List[Any] = []
        for raw in tags:
            if isinstance(raw, dict):
                tag_payload.append(raw)
                continue
            tag = str(raw or "").strip()
            if not tag:
                continue
            tag_payload.append({"name": tag})
        if tag_payload:
            payload["tags"] = tag_payload

    resp = _send(client, "POST", url, json_payload=payload, timeout=30)
    if resp.status_code == 400:
        raw_text = str(resp.text or "")
        text = raw_text.lower()
        # NetBox typically returns 400 for uniqueness violations.
        if "duplicate" in text or "already exists" in text or "unique" in text:
            raise NetBoxConflictError(f"ip address already exists: {address}")
        snippet = raw_text.strip().replace("\n", " ")
        if len(snippet) > 400:
            snippet = snippet[:400] + "..."
        raise RuntimeError(f"netbox reserve_ip validation failed for {address}: {snippet}")
    resp.raise_for_status()
    return resp.json()


def assign_ip_to_interface(client: NetBoxClient, *, ip_id: int, iface_id: int) -> Dict[str, Any]:
    path = f"/api/ipam/ip-addresses/{ip_id}/"
    url = f"{client.base_url}{path}"
    resp = _send(client, "GET", url, timeout=30)
    resp.raise_for_status()
    current = resp.json()

    assigned_object = current.get("assigned_object")
    assigned_type = str(current.get("assigned_object_type") or "").strip()
    assigned_id = None
    if isinstance(assigned_object, dict):
        try:
            assigned_id = int(assigned_object.get("id"))
        except Exception:
            assigned_id = None
    elif current.get("assigned_object_id") is not None:
        try:
            assigned_id = int(current.get("assigned_object_id"))
        except Exception:
            assigned_id = None

    if assigned_object and assigned_type == "virtualization.vminterface" and assigned_id == int(iface_id):
        return current

    payload = {"assigned_object_type": "virtualization.vminterface", "assigned_object_id": iface_id}
    return _patch(client, path, payload)


def set_vm_primary_ip4(client: NetBoxClient, *, vm_id: int, ip_id: int) -> None:
    path = f"/api/virtualization/virtual-machines/{vm_id}/"
    _patch(client, path, {"primary_ip4": ip_id})


def list_vms_in_cluster(client: NetBoxClient, *, cluster_id: int) -> List[Dict[str, Any]]:
    path = "/api/virtualization/virtual-machines/"
    url = f"{client.base_url}{path}"
    params: Dict[str, Any] = {"cluster_id": cluster_id, "limit": 100}
    vms: List[Dict[str, Any]] = []

    while True:
        resp = _send(client, "GET", url, params=params, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        vms.extend(data.get("results", []))

        next_url = data.get("next")
        if not next_url:
            break

        url = next_url
        params = {}

    return vms


def mark_vm_stale(
    client: NetBoxClient,
    *,
    vm_id: int,
    managed_tag: str,
    stale_tag: str,
) -> Dict[str, Any]:
    path = f"/api/virtualization/virtual-machines/{vm_id}/"
    url = f"{client.base_url}{path}"
    resp = _send(client, "GET", url, timeout=30)
    resp.raise_for_status()
    current = resp.json()

    existing_tags_field = current.get("tags", [])
    tag_names: set[str] = set()

    for t in existing_tags_field:
        if isinstance(t, dict):
            name = str(t.get("name") or "").strip()
        else:
            name = str(t).strip()
        if name:
            tag_names.add(name)

    tag_names.add(managed_tag)
    tag_names.add(stale_tag)

    payload: Dict[str, Any] = {"status": "offline"}
    try:
        payload["tags"] = _resolve_tag_ids(client, sorted(tag_names))
    except Exception:
        pass
    return _patch(client, path, payload)


def delete_vm(client: NetBoxClient, *, vm_id: int) -> None:
    path = f"/api/virtualization/virtual-machines/{vm_id}/"
    if client.dry_run:
        print(f"dry-run: DELETE {path}")
        return
    resp = _send(client, "DELETE", f"{client.base_url}{path}", timeout=30)
    if resp.status_code in (200, 202, 204, 404):
        return
    resp.raise_for_status()
