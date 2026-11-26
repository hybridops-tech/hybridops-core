"""Environment admission helpers shared by runtime and drivers."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from hyops.runtime.vault import VaultAuth, read_env


def resolve_required_env(
    inputs: dict[str, Any],
    *,
    key: str = "required_env",
) -> tuple[list[str], str]:
    raw = inputs.get(key)
    if raw is None:
        return [], ""
    if not isinstance(raw, list):
        return [], f"inputs.{key} must be a list when set"

    out: list[str] = []
    seen: set[str] = set()
    for idx, item in enumerate(raw, start=1):
        if not isinstance(item, str) or not item.strip():
            return [], f"inputs.{key}[{idx}] must be a non-empty string"
        token = item.strip()
        if token in seen:
            continue
        seen.add(token)
        out.append(token)
    return out, ""


def merge_vault_env(
    env: dict[str, str],
    runtime_root: Path,
) -> tuple[dict[str, str], str]:
    vault_file = (runtime_root / "vault" / "bootstrap.vault.env").resolve()
    if not vault_file.exists():
        return {}, ""

    try:
        vault_env = read_env(vault_file, VaultAuth())
    except Exception as exc:
        return {}, f"vault decrypt failed: {exc}"

    for key, value in vault_env.items():
        if (env.get(key) or "").strip():
            continue
        env[key] = str(value)
    return vault_env, ""


def missing_env(env: dict[str, str], required: list[str]) -> list[str]:
    return [key for key in required if not (env.get(key) or "").strip()]
