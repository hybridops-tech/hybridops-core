# purpose: Resolve runtime root directory consistently for all commands.
# Architecture Decision: ADR-N/A
# maintainer: HybridOps.Tech

from __future__ import annotations

import os
import re
from pathlib import Path


_ENV_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_-]{0,63}$")


def _validate_env_name(env_name: str) -> str:
    env_name = (env_name or "").strip()
    if not env_name:
        raise ValueError("env name is empty")
    if "/" in env_name or "\\" in env_name or ".." in env_name:
        raise ValueError(f"invalid env name: {env_name!r}")
    if not _ENV_RE.match(env_name):
        raise ValueError(f"invalid env name: {env_name!r}")
    return env_name


def resolve_runtime_root(ns_root: str | None = None, ns_env: str | None = None) -> Path:
    if ns_root and ns_env:
        raise ValueError("--root and --env are mutually exclusive")

    if ns_root:
        return Path(ns_root).expanduser().resolve()

    runtime_env = os.environ.get("HYOPS_RUNTIME_ROOT", "").strip()
    if runtime_env:
        return Path(runtime_env).expanduser().resolve()

    env_name = (ns_env or os.environ.get("HYOPS_ENV", "")).strip()
    if env_name:
        env_name = _validate_env_name(env_name)
        return (Path.home() / ".hybridops" / "envs" / env_name).resolve()

    return (Path.home() / ".hybridops").resolve()


def require_runtime_selection(
    ns_root: str | None = None,
    ns_env: str | None = None,
    *,
    command_label: str = "command",
) -> None:
    if ns_root and ns_env:
        raise ValueError("--root and --env are mutually exclusive")

    if str(ns_root or "").strip():
        return

    if str(os.environ.get("HYOPS_RUNTIME_ROOT", "")).strip():
        return

    env_name = str(ns_env or os.environ.get("HYOPS_ENV", "")).strip()
    if env_name:
        _validate_env_name(env_name)
        return

    raise ValueError(
        f"{command_label} requires explicit runtime selection. "
        "Set --env <name> or --root <path> (or HYOPS_ENV/HYOPS_RUNTIME_ROOT). "
        "Refusing implicit fallback to ~/.hybridops for stateful operations."
    )
