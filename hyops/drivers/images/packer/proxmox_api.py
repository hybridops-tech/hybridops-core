"""Proxmox API helpers for the Packer image driver."""

from __future__ import annotations

import ssl
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

import yaml

from hyops.runtime.coerce import as_positive_int


def proxmox_api_base(url: str) -> str:
    token = str(url or "").strip().rstrip("/")
    if token.endswith("/api2/json"):
        return token
    return f"{token}/api2/json"


def proxmox_request(
    *,
    url: str,
    method: str,
    token_id: str,
    token_secret: str,
    skip_tls: bool,
    path: str,
    params: dict[str, Any] | None = None,
    timeout_s: int = 30,
) -> tuple[Any, str]:
    base = proxmox_api_base(url)
    query = ""
    if isinstance(params, dict) and params:
        encoded = urllib.parse.urlencode({k: str(v) for k, v in params.items()})
        if encoded:
            query = f"?{encoded}"
    endpoint = f"{base}{path}{query}"

    req = urllib.request.Request(endpoint, method=str(method or "GET").upper())
    req.add_header("Authorization", f"PVEAPIToken={token_id}={token_secret}")
    req.add_header("Accept", "application/json")

    context = None
    if skip_tls:
        context = ssl.create_default_context()
        context.check_hostname = False
        context.verify_mode = ssl.CERT_NONE

    try:
        with urllib.request.urlopen(req, timeout=timeout_s, context=context) as resp:
            body = resp.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace") if hasattr(exc, "read") else ""
        detail = body.strip() or str(exc)
        return None, f"HTTP {exc.code} {exc.reason} for {path}: {detail}"
    except Exception as exc:
        return None, f"request failed for {path}: {exc}"

    text = str(body or "").strip()
    if not text:
        return {}, ""
    try:
        return yaml.safe_load(text), ""
    except Exception:
        return text, ""


def proxmox_vmid_exists(
    *,
    proxmox_url: str,
    proxmox_node: str,
    proxmox_token_id: str,
    proxmox_token_secret: str,
    skip_tls: bool,
    vmid: int,
) -> tuple[bool, str]:
    node = urllib.parse.quote(str(proxmox_node).strip(), safe="")
    vmid_token = urllib.parse.quote(str(vmid), safe="")
    status_path = f"/nodes/{node}/qemu/{vmid_token}/status/current"

    _, get_err = proxmox_request(
        url=proxmox_url,
        method="GET",
        token_id=proxmox_token_id,
        token_secret=proxmox_token_secret,
        skip_tls=skip_tls,
        path=status_path,
    )
    if get_err:
        low = get_err.lower()
        if "http 404" in low or "not found" in low or "does not exist" in low:
            return False, ""
        return False, get_err
    return True, ""


def proxmox_name_exists(
    *,
    proxmox_url: str,
    proxmox_node: str,
    proxmox_token_id: str,
    proxmox_token_secret: str,
    skip_tls: bool,
    name: str,
) -> tuple[bool, str]:
    node = urllib.parse.quote(str(proxmox_node).strip(), safe="")
    payload, get_err = proxmox_request(
        url=proxmox_url,
        method="GET",
        token_id=proxmox_token_id,
        token_secret=proxmox_token_secret,
        skip_tls=skip_tls,
        path=f"/nodes/{node}/qemu",
    )
    if get_err:
        return False, get_err

    data: list[dict[str, Any]] = []
    if isinstance(payload, dict):
        raw = payload.get("data")
        if isinstance(raw, list):
            data = [item for item in raw if isinstance(item, dict)]

    needle = str(name or "").strip()
    if not needle:
        return False, "name resolved to empty value"
    for item in data:
        if str(item.get("name") or "").strip() == needle:
            return True, ""
    return False, ""


def proxmox_list_qemu(
    *,
    proxmox_url: str,
    proxmox_node: str,
    proxmox_token_id: str,
    proxmox_token_secret: str,
    skip_tls: bool,
) -> tuple[list[dict[str, Any]], str]:
    node = urllib.parse.quote(str(proxmox_node).strip(), safe="")
    payload, get_err = proxmox_request(
        url=proxmox_url,
        method="GET",
        token_id=proxmox_token_id,
        token_secret=proxmox_token_secret,
        skip_tls=skip_tls,
        path=f"/nodes/{node}/qemu",
    )
    if get_err:
        return [], get_err

    data: list[dict[str, Any]] = []
    if isinstance(payload, dict):
        raw = payload.get("data")
        if isinstance(raw, list):
            data = [item for item in raw if isinstance(item, dict)]
    return data, ""


def proxmox_pick_free_vmid(
    *,
    proxmox_url: str,
    proxmox_node: str,
    proxmox_token_id: str,
    proxmox_token_secret: str,
    skip_tls: bool,
    start_vmid: int,
    end_vmid: int,
) -> tuple[int | None, str]:
    if start_vmid <= 0 or end_vmid <= 0 or end_vmid < start_vmid:
        return None, f"invalid vmid range {start_vmid}-{end_vmid}"

    items, list_err = proxmox_list_qemu(
        proxmox_url=proxmox_url,
        proxmox_node=proxmox_node,
        proxmox_token_id=proxmox_token_id,
        proxmox_token_secret=proxmox_token_secret,
        skip_tls=skip_tls,
    )
    if list_err:
        return None, list_err

    used: set[int] = set()
    for item in items:
        vmid = as_positive_int(item.get("vmid"))
        if vmid is not None:
            used.add(int(vmid))

    for candidate in range(int(start_vmid), int(end_vmid) + 1):
        if candidate not in used:
            return candidate, ""
    return None, f"no free vmid found in range {start_vmid}-{end_vmid}"


def proxmox_pool_exists(
    *,
    proxmox_url: str,
    proxmox_token_id: str,
    proxmox_token_secret: str,
    skip_tls: bool,
    pool: str,
) -> tuple[bool, str]:
    pool_name = str(pool or "").strip()
    if not pool_name:
        return False, "pool resolved to empty value"

    pool_token = urllib.parse.quote(pool_name, safe="")
    _, get_err = proxmox_request(
        url=proxmox_url,
        method="GET",
        token_id=proxmox_token_id,
        token_secret=proxmox_token_secret,
        skip_tls=skip_tls,
        path=f"/pools/{pool_token}",
    )
    if get_err:
        low = get_err.lower()
        if "http 404" in low or "not found" in low or "does not exist" in low:
            return False, ""
        return False, get_err
    return True, ""


def proxmox_resolve_vmid_by_name(
    *,
    proxmox_url: str,
    proxmox_node: str,
    proxmox_token_id: str,
    proxmox_token_secret: str,
    skip_tls: bool,
    name: str,
) -> tuple[int | None, str]:
    node = urllib.parse.quote(str(proxmox_node).strip(), safe="")
    payload, get_err = proxmox_request(
        url=proxmox_url,
        method="GET",
        token_id=proxmox_token_id,
        token_secret=proxmox_token_secret,
        skip_tls=skip_tls,
        path=f"/nodes/{node}/qemu",
    )
    if get_err:
        return None, get_err

    data: list[dict[str, Any]] = []
    if isinstance(payload, dict):
        raw = payload.get("data")
        if isinstance(raw, list):
            data = [item for item in raw if isinstance(item, dict)]

    needle = str(name or "").strip()
    if not needle:
        return None, "name resolved to empty value"

    matches = [item for item in data if str(item.get("name") or "").strip() == needle]
    if not matches:
        return None, ""
    if len(matches) > 1:
        return None, f"multiple VMs found with name={needle}; set inputs.vmid explicitly"

    resolved = as_positive_int(matches[0].get("vmid"))
    if resolved is None:
        return None, f"failed to resolve vmid for name={needle}"
    return int(resolved), ""


def proxmox_wait_task(
    *,
    proxmox_url: str,
    proxmox_node: str,
    proxmox_token_id: str,
    proxmox_token_secret: str,
    skip_tls: bool,
    upid: str,
    timeout_s: int = 300,
    poll_s: float = 2.0,
) -> tuple[dict[str, Any], str]:
    node = urllib.parse.quote(str(proxmox_node).strip(), safe="")
    upid_token = urllib.parse.quote(str(upid).strip(), safe="")
    path = f"/nodes/{node}/tasks/{upid_token}/status"

    deadline = time.time() + max(1, int(timeout_s))
    last_payload: dict[str, Any] = {}
    while time.time() < deadline:
        payload, get_err = proxmox_request(
            url=proxmox_url,
            method="GET",
            token_id=proxmox_token_id,
            token_secret=proxmox_token_secret,
            skip_tls=skip_tls,
            path=path,
            timeout_s=20,
        )
        if get_err:
            return {}, get_err

        if isinstance(payload, dict):
            data = payload.get("data")
            if isinstance(data, dict):
                last_payload = data
                status = str(data.get("status") or "").strip().lower()
                if status == "stopped":
                    exitstatus = str(data.get("exitstatus") or "").strip().upper()
                    if exitstatus in ("", "OK"):
                        return last_payload, ""
                    return last_payload, f"task {upid} finished with exitstatus={exitstatus}"
        time.sleep(max(0.2, float(poll_s)))

    return last_payload, f"task {upid} did not complete within {int(timeout_s)}s"


def proxmox_clone_vm(
    *,
    proxmox_url: str,
    proxmox_node: str,
    proxmox_token_id: str,
    proxmox_token_secret: str,
    skip_tls: bool,
    source_vmid: int,
    new_vmid: int,
    name: str,
    full: bool = True,
    timeout_s: int = 600,
) -> tuple[dict[str, Any], str]:
    node = urllib.parse.quote(str(proxmox_node).strip(), safe="")
    source_token = urllib.parse.quote(str(source_vmid), safe="")
    payload, post_err = proxmox_request(
        url=proxmox_url,
        method="POST",
        token_id=proxmox_token_id,
        token_secret=proxmox_token_secret,
        skip_tls=skip_tls,
        path=f"/nodes/{node}/qemu/{source_token}/clone",
        params={"newid": int(new_vmid), "name": str(name or "").strip(), "full": 1 if full else 0},
        timeout_s=60,
    )
    if post_err:
        return {}, post_err

    upid = str(payload.get("data") or "").strip() if isinstance(payload, dict) else ""
    if not upid:
        return {"clone_requested": True}, ""
    task_data, wait_err = proxmox_wait_task(
        proxmox_url=proxmox_url,
        proxmox_node=proxmox_node,
        proxmox_token_id=proxmox_token_id,
        proxmox_token_secret=proxmox_token_secret,
        skip_tls=skip_tls,
        upid=upid,
        timeout_s=int(timeout_s),
        poll_s=2.0,
    )
    if wait_err:
        return {"upid": upid, "task": task_data}, wait_err
    return {"upid": upid, "task": task_data}, ""


def proxmox_start_vm(
    *,
    proxmox_url: str,
    proxmox_node: str,
    proxmox_token_id: str,
    proxmox_token_secret: str,
    skip_tls: bool,
    vmid: int,
    timeout_s: int = 300,
) -> tuple[dict[str, Any], str]:
    node = urllib.parse.quote(str(proxmox_node).strip(), safe="")
    vmid_token = urllib.parse.quote(str(vmid), safe="")
    payload, post_err = proxmox_request(
        url=proxmox_url,
        method="POST",
        token_id=proxmox_token_id,
        token_secret=proxmox_token_secret,
        skip_tls=skip_tls,
        path=f"/nodes/{node}/qemu/{vmid_token}/status/start",
        timeout_s=30,
    )
    if post_err:
        if "already running" in post_err.lower():
            return {"already_running": True}, ""
        return {}, post_err

    upid = str(payload.get("data") or "").strip() if isinstance(payload, dict) else ""
    if not upid:
        return {"start_requested": True}, ""
    task_data, wait_err = proxmox_wait_task(
        proxmox_url=proxmox_url,
        proxmox_node=proxmox_node,
        proxmox_token_id=proxmox_token_id,
        proxmox_token_secret=proxmox_token_secret,
        skip_tls=skip_tls,
        upid=upid,
        timeout_s=int(timeout_s),
        poll_s=1.0,
    )
    if wait_err:
        return {"upid": upid, "task": task_data}, wait_err
    return {"upid": upid, "task": task_data}, ""


def proxmox_agent_wait_first_ipv4(
    *,
    proxmox_url: str,
    proxmox_node: str,
    proxmox_token_id: str,
    proxmox_token_secret: str,
    skip_tls: bool,
    vmid: int,
    timeout_s: int = 300,
    poll_s: float = 5.0,
) -> tuple[str, dict[str, Any], str]:
    node = urllib.parse.quote(str(proxmox_node).strip(), safe="")
    vmid_token = urllib.parse.quote(str(vmid), safe="")
    path = f"/nodes/{node}/qemu/{vmid_token}/agent/network-get-interfaces"

    deadline = time.time() + max(5, int(timeout_s))
    last_payload: dict[str, Any] = {}
    last_err = ""
    while time.time() < deadline:
        payload, get_err = proxmox_request(
            url=proxmox_url,
            method="GET",
            token_id=proxmox_token_id,
            token_secret=proxmox_token_secret,
            skip_tls=skip_tls,
            path=path,
            timeout_s=20,
        )
        if get_err:
            last_err = get_err
            time.sleep(max(0.5, float(poll_s)))
            continue

        if isinstance(payload, dict):
            data = payload.get("data")
            if isinstance(data, dict):
                last_payload = data
                result = data.get("result")
                if isinstance(result, list):
                    for iface in result:
                        if not isinstance(iface, dict):
                            continue
                        ip_list = iface.get("ip-addresses")
                        if not isinstance(ip_list, list):
                            continue
                        for ip_info in ip_list:
                            if not isinstance(ip_info, dict):
                                continue
                            ip = str(ip_info.get("ip-address") or "").strip()
                            family = str(ip_info.get("ip-address-type") or "").strip().lower()
                            if family != "ipv4" or not ip or ip.startswith("127."):
                                continue
                            return ip, last_payload, ""
        time.sleep(max(0.5, float(poll_s)))

    if last_err:
        return "", last_payload, f"guest-agent ip probe timeout after {int(timeout_s)}s (last_error={last_err})"
    return "", last_payload, f"guest-agent ip probe timeout after {int(timeout_s)}s"


def proxmox_agent_get_osinfo(
    *,
    proxmox_url: str,
    proxmox_node: str,
    proxmox_token_id: str,
    proxmox_token_secret: str,
    skip_tls: bool,
    vmid: int,
) -> tuple[dict[str, Any], str]:
    node = urllib.parse.quote(str(proxmox_node).strip(), safe="")
    vmid_token = urllib.parse.quote(str(vmid), safe="")
    payload, get_err = proxmox_request(
        url=proxmox_url,
        method="GET",
        token_id=proxmox_token_id,
        token_secret=proxmox_token_secret,
        skip_tls=skip_tls,
        path=f"/nodes/{node}/qemu/{vmid_token}/agent/get-osinfo",
        timeout_s=20,
    )
    if get_err:
        return {}, get_err
    if isinstance(payload, dict):
        data = payload.get("data")
        if isinstance(data, dict):
            result = data.get("result")
            if isinstance(result, dict):
                return result, ""
    return {}, ""


def purge_template_vm(
    *,
    proxmox_url: str,
    proxmox_node: str,
    proxmox_token_id: str,
    proxmox_token_secret: str,
    skip_tls: bool,
    vmid: int,
) -> tuple[list[str], str]:
    warnings: list[str] = []
    node = urllib.parse.quote(str(proxmox_node).strip(), safe="")
    vmid_token = urllib.parse.quote(str(vmid), safe="")
    vm_path = f"/nodes/{node}/qemu/{vmid_token}"
    status_path = f"{vm_path}/status/current"

    payload, get_err = proxmox_request(
        url=proxmox_url,
        method="GET",
        token_id=proxmox_token_id,
        token_secret=proxmox_token_secret,
        skip_tls=skip_tls,
        path=status_path,
    )
    if get_err:
        low = get_err.lower()
        if "http 404" in low or "not found" in low or "does not exist" in low:
            warnings.append(f"template vmid={vmid} not found; nothing to purge")
            return warnings, ""
        return warnings, f"failed to read template status vmid={vmid}: {get_err}"

    status = ""
    if isinstance(payload, dict):
        data = payload.get("data")
        if isinstance(data, dict):
            status = str(data.get("status") or "").strip().lower()

    if status == "running":
        _, stop_err = proxmox_request(
            url=proxmox_url,
            method="POST",
            token_id=proxmox_token_id,
            token_secret=proxmox_token_secret,
            skip_tls=skip_tls,
            path=f"{vm_path}/status/stop",
            timeout_s=20,
        )
        if stop_err:
            warnings.append(f"stop requested before purge but returned: {stop_err}")
        else:
            deadline = time.time() + 60.0
            while time.time() < deadline:
                probe, probe_err = proxmox_request(
                    url=proxmox_url,
                    method="GET",
                    token_id=proxmox_token_id,
                    token_secret=proxmox_token_secret,
                    skip_tls=skip_tls,
                    path=status_path,
                    timeout_s=15,
                )
                if probe_err:
                    warnings.append(f"status probe after stop returned: {probe_err}")
                    break
                state = ""
                if isinstance(probe, dict):
                    data = probe.get("data")
                    if isinstance(data, dict):
                        state = str(data.get("status") or "").strip().lower()
                if state != "running":
                    break
                time.sleep(2.0)

    _, delete_err = proxmox_request(
        url=proxmox_url,
        method="DELETE",
        token_id=proxmox_token_id,
        token_secret=proxmox_token_secret,
        skip_tls=skip_tls,
        path=vm_path,
        params={"purge": 1, "destroy-unreferenced-disks": 1},
        timeout_s=60,
    )
    if delete_err:
        low = delete_err.lower()
        if "http 404" in low or "not found" in low or "does not exist" in low:
            warnings.append(f"template vmid={vmid} not found during delete; nothing to purge")
            return warnings, ""
        return warnings, f"failed to purge template vmid={vmid}: {delete_err}"

    deadline = time.time() + 300.0
    while time.time() < deadline:
        exists, probe_err = proxmox_vmid_exists(
            proxmox_url=proxmox_url,
            proxmox_node=proxmox_node,
            proxmox_token_id=proxmox_token_id,
            proxmox_token_secret=proxmox_token_secret,
            skip_tls=skip_tls,
            vmid=int(vmid),
        )
        if probe_err:
            warnings.append(f"purge verification probe returned: {probe_err}")
            time.sleep(3.0)
            continue
        if not exists:
            break
        time.sleep(3.0)

    if time.time() >= deadline:
        exists, probe_err = proxmox_vmid_exists(
            proxmox_url=proxmox_url,
            proxmox_node=proxmox_node,
            proxmox_token_id=proxmox_token_id,
            proxmox_token_secret=proxmox_token_secret,
            skip_tls=skip_tls,
            vmid=int(vmid),
        )
        if probe_err:
            return warnings, f"purge verification failed for vmid={vmid}: {probe_err}"
        if exists:
            return warnings, f"purge did not complete within 300s for template vmid={vmid}"

    warnings.append(f"purged template vmid={vmid}")
    return warnings, ""
