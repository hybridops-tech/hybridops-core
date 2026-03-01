"""Module input helpers.

purpose: Shared low-level input parsing and env override helpers for module resolution.
Architecture Decision: ADR-N/A (module resolution)
maintainer: HybridOps.Studio
"""

from __future__ import annotations

from typing import Any
import json
import os
import re


_INPUT_SEG_RE = re.compile(r"^[a-zA-Z0-9_-]+$")


def try_json(value: str) -> Any:
    v = value.strip()
    if v == "":
        return ""
    try:
        return json.loads(v)
    except Exception:
        return value


def set_nested(dst: dict[str, Any], path: list[str], value: Any) -> None:
    cur: dict[str, Any] = dst
    for key in path[:-1]:
        nxt = cur.get(key)
        if not isinstance(nxt, dict):
            nxt = {}
            cur[key] = nxt
        cur = nxt
    cur[path[-1]] = value


def try_get_nested(src: dict[str, Any], key: str) -> tuple[bool, Any]:
    """Best-effort output lookup.

    Dependency imports historically treated output keys as flat strings (including dots,
    e.g. "cap.db.pgcore"). We keep that behavior first, then fall back to nested lookup
    using '.' as a path separator only when the flat key is absent.

    This enables imports like "apps.netbox.db_host" when a module publishes a structured
    output under "apps": {...}.
    """
    if key in src:
        return True, src.get(key)

    if "." not in key:
        return False, None

    cur: Any = src
    for part in [p for p in key.split(".") if p]:
        if not isinstance(cur, dict) or part not in cur:
            return False, None
        cur = cur.get(part)
    return True, cur


def parse_input_path(path: str) -> list[str]:
    parts = [p for p in (path or "").strip().split(".") if p]
    if not parts:
        raise ValueError(f"invalid input path: {path!r}")

    for part in parts:
        if not _INPUT_SEG_RE.fullmatch(part):
            raise ValueError(f"invalid input path segment: {part!r}")

    return parts


def apply_env_overrides(inputs: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = dict(inputs)

    raw_json = os.environ.get("HYOPS_INPUTS_JSON", "").strip()
    if raw_json:
        blob = try_json(raw_json)
        if not isinstance(blob, dict):
            raise ValueError("HYOPS_INPUTS_JSON must be a JSON object")
        out.update(blob)

    prefix = "HYOPS_INPUT_"
    for k, v in os.environ.items():
        if not k.startswith(prefix):
            continue

        key = k[len(prefix) :].strip()
        if not key:
            continue

        # Nested keys use __ as a separator, e.g. HYOPS_INPUT_network__cidr="10.0.0.0/16"
        path = [p.lower() for p in key.split("__") if p]
        if not path:
            continue

        set_nested(out, path, try_json(v))

    return out

