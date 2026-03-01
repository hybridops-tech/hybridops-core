"""
purpose: Provider-aware naming helpers for env-scoped resources.
Architecture Decision: ADR-N/A (naming policy)
maintainer: HybridOps.Studio
"""

from __future__ import annotations

import re
from typing import Any


_ENV_CODE_RE = re.compile(r"^[a-z][a-z0-9]{0,7}$")


def resolve_env_code(env_name: str | None, *, naming_policy: dict[str, Any] | None = None) -> tuple[str, str]:
    """
    Resolve an env code used for name scoping.

    Env code should be short and provider-safe. For Proxmox SDN IDs we keep it
    alnum and start with a letter. Profiles may override via:
      policy.naming.env.code_map
      policy.naming.env.default_code
    """
    name = str(env_name or "").strip()
    if not name:
        return "", ""

    policy: dict[str, Any] = naming_policy if isinstance(naming_policy, dict) else {}

    env_policy_raw = policy.get("env")
    env_policy: dict[str, Any]
    if isinstance(env_policy_raw, dict):
        env_policy = env_policy_raw
    else:
        env_policy = {}

    code_map_raw = env_policy.get("code_map")
    code_map: dict[str, Any]
    if isinstance(code_map_raw, dict):
        code_map = code_map_raw
    else:
        code_map = {}

    raw = str(code_map.get(name) or "").strip().lower()
    if not raw:
        raw = str(env_policy.get("default_code") or "").strip().lower()
    if not raw:
        raw = name[0:1].lower()

    raw = re.sub(r"[^a-z0-9]+", "", raw)
    if not _ENV_CODE_RE.match(raw):
        return "", f"invalid env code derived for env={name!r}: {raw!r}"

    return raw, ""


def compose_label(*, env_code: str, base: str, sep: str = "-") -> str:
    c = str(env_code or "").strip()
    b = str(base or "").strip()
    if not c or not b:
        return b
    return f"{c}{sep}{b}"


def compose_compact_id(
    *,
    env_code: str,
    base: str,
    max_len: int,
    allowed_re: re.Pattern[str],
) -> tuple[str, str]:
    c = str(env_code or "").strip()
    b = str(base or "").strip()
    if not c or not b:
        return b, ""

    candidate = f"{c}{b}"
    if len(candidate) > int(max_len):
        return "", f"env-scoped id '{candidate}' exceeds max length {int(max_len)} (base={b!r}, env_code={c!r})"
    if not allowed_re.match(candidate):
        return "", f"env-scoped id '{candidate}' violates provider constraints"

    return candidate, ""
