#!/usr/bin/env python3
"""
purpose: Cloudflare worker steering helper for platform/network/cloudflare-traffic-steering.
maintainer: HybridOps
"""

from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any


def _fail(message: str, *, code: int = 1) -> None:
    raise SystemExit(message)


def _load_config(path: str) -> dict[str, Any]:
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    except FileNotFoundError:
        _fail(f"config file not found: {path}")
    except json.JSONDecodeError as exc:
        _fail(f"config file is not valid JSON: {exc}")
    if not isinstance(payload, dict):
        _fail("config must be a mapping")
    return payload


def _burst_weight(config: dict[str, Any]) -> int:
    desired = str(config.get("desired") or "primary").strip().lower()
    if desired == "primary":
        return 0
    if desired == "burst":
        return 100
    return int(config.get("balanced_burst_weight_pct") or 50)


def _request(
    method: str,
    url: str,
    *,
    token: str = "",
    body: bytes | None = None,
    headers: dict[str, str] | None = None,
    expected: tuple[int, ...] = (200,),
) -> dict[str, Any]:
    req_headers = {"accept": "application/json"}
    if token:
        req_headers["authorization"] = f"Bearer {token}"
    if headers:
        req_headers.update(headers)
    request = urllib.request.Request(url, data=body, headers=req_headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            status = response.getcode()
            payload = response.read()
    except urllib.error.HTTPError as exc:
        status = exc.code
        payload = exc.read()
    except urllib.error.URLError as exc:
        _fail(f"request failed for {url}: {exc}")
    if status not in expected:
        _fail(f"unexpected status {status} for {method} {url}: {payload.decode('utf-8', 'replace')}")
    if not payload:
        return {}
    decoded = json.loads(payload.decode("utf-8"))
    if isinstance(decoded, dict) and decoded.get("success") is False:
        _fail(f"cloudflare API error for {method} {url}: {json.dumps(decoded)}")
    return decoded


def _discover_account_id(token: str, desired_name: str) -> str:
    payload = _request("GET", "https://api.cloudflare.com/client/v4/memberships", token=token)
    results = payload.get("result") or []
    account_ids: list[tuple[str, str]] = []
    for item in results:
        if not isinstance(item, dict):
            continue
        account = item.get("account") or {}
        account_id = str(account.get("id") or "").strip()
        account_name = str(account.get("name") or "").strip()
        if account_id:
            account_ids.append((account_id, account_name))
    if desired_name:
        matches = [item for item in account_ids if item[1] == desired_name]
        if len(matches) == 1:
            return matches[0][0]
        _fail(f"could not resolve Cloudflare account named {desired_name!r}")
    unique = {item[0] for item in account_ids}
    if len(unique) == 1:
        return next(iter(unique))
    _fail("cloudflare_account_id is required when the token can access multiple accounts")


def _zone_id(token: str, zone_name: str) -> str:
    query = urllib.parse.urlencode({"name": zone_name})
    payload = _request("GET", f"https://api.cloudflare.com/client/v4/zones?{query}", token=token)
    results = payload.get("result") or []
    if len(results) != 1:
        _fail(f"expected exactly one zone for {zone_name}, found {len(results)}")
    zone_id = str((results[0] or {}).get("id") or "").strip()
    if not zone_id:
        _fail(f"zone {zone_name} did not return an id")
    return zone_id


def _worker_script(config: dict[str, Any]) -> str:
    payload = {
        "worker_name": str(config.get("worker_name") or ""),
        "zone_name": str(config.get("zone_name") or ""),
        "hostname": str(config.get("hostname") or ""),
        "route_pattern": str(config.get("route_pattern") or ""),
        "primary_origin_url": str(config.get("primary_origin_url") or "").rstrip("/"),
        "burst_origin_url": str(config.get("burst_origin_url") or "").rstrip("/"),
        "desired": str(config.get("desired") or "primary").strip().lower(),
        "burst_weight_pct": _burst_weight(config),
        "cookie_name": str(config.get("cookie_name") or "__hyops_burst_lane"),
        "cookie_ttl_s": int(config.get("cookie_ttl_s") or 900),
        "root_redirect_path": str(config.get("root_redirect_path") or "/"),
        "forward_prefixes": list(config.get("forward_prefixes") or []),
        "status_url": f"https://{str(config.get('hostname') or '').strip()}/__burst/status",
        "version": "traffic-steering-v1",
    }
    json_payload = json.dumps(payload, sort_keys=True)
    return f"""const CONFIG = {json_payload};

function normalizeLane(value) {{
  const token = String(value || "").trim().toLowerCase();
  return token === "primary" || token === "burst" ? token : "";
}}

function parseCookie(header, name) {{
  const raw = String(header || "");
  for (const part of raw.split(";")) {{
    const [key, ...rest] = part.trim().split("=");
    if (key === name) {{
      return normalizeLane(rest.join("="));
    }}
  }}
  return "";
}}

function chooseLane(requestUrl, cookieHeader) {{
  const override = normalizeLane(requestUrl.searchParams.get("__hyops_origin"));
  if (override) {{
    return {{ lane: override, source: "override" }};
  }}
  const cookieLane = parseCookie(cookieHeader, CONFIG.cookie_name);
  if (cookieLane) {{
    return {{ lane: cookieLane, source: "cookie" }};
  }}
  if (CONFIG.burst_weight_pct <= 0) {{
    return {{ lane: "primary", source: "weight" }};
  }}
  if (CONFIG.burst_weight_pct >= 100) {{
    return {{ lane: "burst", source: "weight" }};
  }}
  const sample = new Uint32Array(1);
  crypto.getRandomValues(sample);
  return {{
    lane: (sample[0] % 100) < CONFIG.burst_weight_pct ? "burst" : "primary",
    source: "weight",
  }};
}}

function pathAllowed(pathname) {{
  return CONFIG.forward_prefixes.some((prefix) => pathname === prefix || pathname.startsWith(prefix + "/"));
}}

function buildStatusBody() {{
  return {{
    status: "live-ok",
    provider: "cloudflare-worker",
    worker_name: CONFIG.worker_name,
    zone_name: CONFIG.zone_name,
    hostname: CONFIG.hostname,
    route_pattern: CONFIG.route_pattern,
    desired: CONFIG.desired,
    burst_weight_pct: CONFIG.burst_weight_pct,
    primary_origin_url: CONFIG.primary_origin_url,
    burst_origin_url: CONFIG.burst_origin_url,
    cookie_name: CONFIG.cookie_name,
    cookie_ttl_s: CONFIG.cookie_ttl_s,
    root_redirect_path: CONFIG.root_redirect_path,
    forward_prefixes: CONFIG.forward_prefixes,
    status_url: CONFIG.status_url,
    route_ready: true,
    version: CONFIG.version,
  }};
}}

async function handle(request) {{
  const url = new URL(request.url);
  if (url.pathname === "/__burst/status") {{
    return new Response(JSON.stringify(buildStatusBody(), null, 2), {{
      status: 200,
      headers: {{
        "content-type": "application/json; charset=utf-8",
        "cache-control": "no-store",
      }},
    }});
  }}

  if (url.pathname === "/") {{
    return Response.redirect(url.origin + CONFIG.root_redirect_path, 302);
  }}

  if (!pathAllowed(url.pathname)) {{
    return new Response("Not Found", {{ status: 404 }});
  }}

  const choice = chooseLane(url, request.headers.get("cookie"));
  const originBase = new URL(choice.lane === "burst" ? CONFIG.burst_origin_url : CONFIG.primary_origin_url);
  const upstreamUrl = new URL(url.pathname + url.search, originBase);
  const headers = new Headers(request.headers);
  headers.set("x-forwarded-host", url.host);
  headers.set("x-forwarded-proto", url.protocol.replace(":", ""));
  headers.set("x-hybridops-public-host", url.host);

  const upstreamRequest = new Request(upstreamUrl.toString(), {{
    method: request.method,
    headers,
    body: request.method === "GET" || request.method === "HEAD" ? undefined : request.body,
    redirect: "manual",
  }});

  const upstreamResponse = await fetch(upstreamRequest);
  const response = new Response(upstreamResponse.body, upstreamResponse);
  response.headers.set("x-hybridops-burst-lane", choice.lane);
  response.headers.set("x-hybridops-burst-source", choice.source);
  response.headers.set("x-hybridops-burst-desired", CONFIG.desired);
  response.headers.set("x-hybridops-burst-weight", String(CONFIG.burst_weight_pct));
  response.headers.set("x-hybridops-primary-origin", CONFIG.primary_origin_url);
  response.headers.set("x-hybridops-burst-origin", CONFIG.burst_origin_url);
  response.headers.append(
    "set-cookie",
    `${{CONFIG.cookie_name}}=${{choice.lane}}; Max-Age=${{CONFIG.cookie_ttl_s}}; Path=/; Secure; HttpOnly; SameSite=Lax`
  );
  return response;
}}

addEventListener("fetch", (event) => {{
  event.respondWith(handle(event.request));
}});
"""


def _upload_worker(token: str, account_id: str, config: dict[str, Any]) -> None:
    body = _worker_script(config).encode("utf-8")
    url = f"https://api.cloudflare.com/client/v4/accounts/{account_id}/workers/scripts/{config['worker_name']}"
    _request(
        "PUT",
        url,
        token=token,
        body=body,
        headers={"content-type": "application/javascript"},
        expected=(200,),
    )


def _list_routes(token: str, zone_id: str) -> list[dict[str, Any]]:
    payload = _request(
        "GET",
        f"https://api.cloudflare.com/client/v4/zones/{zone_id}/workers/routes",
        token=token,
    )
    results = payload.get("result") or []
    return [item for item in results if isinstance(item, dict)]


def _upsert_route(token: str, zone_id: str, pattern: str, script_name: str) -> None:
    routes = _list_routes(token, zone_id)
    for route in routes:
        if str(route.get("pattern") or "") == pattern:
            if str(route.get("script") or "") == script_name:
                return
            route_id = str(route.get("id") or "").strip()
            if route_id:
                _request(
                    "DELETE",
                    f"https://api.cloudflare.com/client/v4/zones/{zone_id}/workers/routes/{route_id}",
                    token=token,
                    expected=(200,),
                )
    payload = json.dumps({"pattern": pattern, "script": script_name}).encode("utf-8")
    _request(
        "POST",
        f"https://api.cloudflare.com/client/v4/zones/{zone_id}/workers/routes",
        token=token,
        body=payload,
        headers={"content-type": "application/json"},
        expected=(200,),
    )


def _upsert_dns_record(token: str, zone_id: str, config: dict[str, Any]) -> None:
    if not config.get("ensure_dns_record"):
        return
    record_type = str(config.get("dns_record_type") or "CNAME").upper()
    name = str(config.get("dns_record_name") or "").strip()
    target = str(config.get("dns_record_target") or "").strip()
    proxied = bool(config.get("dns_record_proxied", True))
    if not name or not target:
        _fail("dns_record_name and dns_record_target are required when ensure_dns_record=true")
    query = urllib.parse.urlencode({"name": name, "type": record_type})
    payload = _request(
        "GET",
        f"https://api.cloudflare.com/client/v4/zones/{zone_id}/dns_records?{query}",
        token=token,
    )
    results = payload.get("result") or []
    body = json.dumps(
        {
            "type": record_type,
            "name": name,
            "content": target,
            "proxied": proxied,
        }
    ).encode("utf-8")
    if results:
        record_id = str((results[0] or {}).get("id") or "").strip()
        if record_id:
            _request(
                "PUT",
                f"https://api.cloudflare.com/client/v4/zones/{zone_id}/dns_records/{record_id}",
                token=token,
                body=body,
                headers={"content-type": "application/json"},
                expected=(200,),
            )
            return
    _request(
        "POST",
        f"https://api.cloudflare.com/client/v4/zones/{zone_id}/dns_records",
        token=token,
        body=body,
        headers={"content-type": "application/json"},
        expected=(200,),
    )


def _delete_dns_record(token: str, zone_id: str, config: dict[str, Any]) -> None:
    if not config.get("delete_dns_record_on_destroy"):
        return
    record_type = str(config.get("dns_record_type") or "CNAME").upper()
    name = str(config.get("dns_record_name") or "").strip()
    if not name:
        return
    query = urllib.parse.urlencode({"name": name, "type": record_type})
    payload = _request(
        "GET",
        f"https://api.cloudflare.com/client/v4/zones/{zone_id}/dns_records?{query}",
        token=token,
    )
    for item in payload.get("result") or []:
        record_id = str((item or {}).get("id") or "").strip()
        if record_id:
            _request(
                "DELETE",
                f"https://api.cloudflare.com/client/v4/zones/{zone_id}/dns_records/{record_id}",
                token=token,
                expected=(200,),
            )


def _delete_route(token: str, zone_id: str, pattern: str) -> None:
    routes = _list_routes(token, zone_id)
    for route in routes:
        if str(route.get("pattern") or "") != pattern:
            continue
        route_id = str(route.get("id") or "").strip()
        if route_id:
            _request(
                "DELETE",
                f"https://api.cloudflare.com/client/v4/zones/{zone_id}/workers/routes/{route_id}",
                token=token,
                expected=(200,),
            )


def _delete_worker(token: str, account_id: str, worker_name: str) -> None:
    _request(
        "DELETE",
        f"https://api.cloudflare.com/client/v4/accounts/{account_id}/workers/scripts/{worker_name}",
        token=token,
        expected=(200, 404),
    )


def _status_url(config: dict[str, Any]) -> str:
    return f"https://{str(config.get('hostname') or '').strip()}/__burst/status"


def _public_status(config: dict[str, Any]) -> dict[str, Any]:
    timeout_s = int(config.get("status_timeout_s") or 10)
    retries = int(config.get("status_retries") or 1)
    delay_s = int(config.get("status_retry_delay_s") or 1)
    url = _status_url(config)
    last_error = ""
    for attempt in range(1, retries + 1):
        try:
            request = urllib.request.Request(
                url,
                headers={
                    "accept": "application/json",
                    "user-agent": "HybridOps status probe/1.0",
                },
                method="GET",
            )
            with urllib.request.urlopen(request, timeout=timeout_s) as response:
                payload = json.loads(response.read().decode("utf-8"))
            if isinstance(payload, dict):
                payload.setdefault("status_url", url)
                return payload
            last_error = f"status endpoint returned non-object payload on attempt {attempt}"
        except Exception as exc:  # noqa: BLE001
            last_error = f"{type(exc).__name__}: {exc}"
        if attempt < retries:
            time.sleep(delay_s)
    _fail(f"failed to read live steering status from {url}: {last_error}")


def _verify_status(config: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
    expected = {
        "desired": str(config.get("desired") or "primary").strip().lower(),
        "burst_weight_pct": _burst_weight(config),
        "primary_origin_url": str(config.get("primary_origin_url") or "").rstrip("/"),
        "burst_origin_url": str(config.get("burst_origin_url") or "").rstrip("/"),
        "hostname": str(config.get("hostname") or "").strip(),
        "route_pattern": str(config.get("route_pattern") or f"{str(config.get('hostname') or '').strip()}/*"),
        "worker_name": str(config.get("worker_name") or "").strip(),
    }
    for key, expected_value in expected.items():
        actual = payload.get(key)
        if actual != expected_value:
            _fail(f"live steering status mismatch for {key}: expected {expected_value!r}, got {actual!r}")
    payload["status"] = "live-ok"
    payload["route_ready"] = True
    return payload


def _require_token(config: dict[str, Any]) -> str:
    token_env = str(config.get("cloudflare_api_token_env") or "").strip()
    token = str(os.environ.get(token_env) or "").strip()
    if not token:
        _fail(f"missing Cloudflare API token in env var {token_env}")
    return token


def _account_id(token: str, config: dict[str, Any]) -> str:
    explicit = str(config.get("cloudflare_account_id") or "").strip()
    if explicit:
        return explicit
    return _discover_account_id(token, str(config.get("cloudflare_account_name") or "").strip())


def _bootstrap(config: dict[str, Any]) -> dict[str, Any]:
    token = _require_token(config)
    account_id = _account_id(token, config)
    zone_id = _zone_id(token, str(config.get("zone_name") or "").strip())
    _upload_worker(token, account_id, config)
    _upsert_route(token, zone_id, str(config.get("route_pattern") or ""), str(config.get("worker_name") or ""))
    _upsert_dns_record(token, zone_id, config)
    payload = _public_status(config)
    payload = _verify_status(config, payload)
    payload["account_id"] = account_id
    payload["zone_id"] = zone_id
    return payload


def _status(config: dict[str, Any]) -> dict[str, Any]:
    payload = _public_status(config)
    return _verify_status(config, payload)


def _absent(config: dict[str, Any]) -> dict[str, Any]:
    token = _require_token(config)
    account_id = _account_id(token, config)
    zone_id = _zone_id(token, str(config.get("zone_name") or "").strip())
    _delete_route(token, zone_id, str(config.get("route_pattern") or ""))
    _delete_dns_record(token, zone_id, config)
    if bool(config.get("delete_worker_on_destroy", False)):
        _delete_worker(token, account_id, str(config.get("worker_name") or ""))
    return {
        "status": "absent",
        "provider": "cloudflare-worker",
        "hostname": str(config.get("hostname") or "").strip(),
        "route_pattern": str(config.get("route_pattern") or "").strip(),
        "worker_name": str(config.get("worker_name") or "").strip(),
        "zone_name": str(config.get("zone_name") or "").strip(),
        "route_ready": False,
    }


def main(argv: list[str]) -> int:
    if len(argv) != 3 or argv[1] not in {"bootstrap", "status", "absent"}:
        print("usage: manage-cloudflare-traffic-steering.py <bootstrap|status|absent> <config.json>", file=sys.stderr)
        return 2
    action = argv[1]
    config = _load_config(argv[2])
    if not str(config.get("route_pattern") or "").strip():
        config["route_pattern"] = f"{str(config.get('hostname') or '').strip()}/*"
    if action == "bootstrap":
        payload = _bootstrap(config)
    elif action == "status":
        payload = _status(config)
    else:
        payload = _absent(config)
    print(json.dumps(payload, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
