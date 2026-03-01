"""Source root helpers.

purpose: Resolve module/blueprint/input paths from cwd or installed HYOPS_CORE_ROOT.
Architecture Decision: ADR-N/A (path discovery)
maintainer: HybridOps.Studio
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path


def discover_core_root(explicit: str | Path | None = None) -> Path | None:
    """Best-effort discovery of the HybridOps core source root."""
    if explicit:
        return Path(str(explicit)).expanduser().resolve()

    env_root = str(os.environ.get("HYOPS_CORE_ROOT") or "").strip()
    if env_root:
        return Path(env_root).expanduser().resolve()

    cur = Path.cwd().resolve()
    for _ in range(0, 10):
        if (cur / "hyops").exists() and (cur / "modules").exists():
            return cur
        if cur.parent == cur:
            break
        cur = cur.parent

    try:
        r = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            text=True,
            capture_output=True,
            check=False,
        )
        if r.returncode == 0:
            root = Path(r.stdout.strip()).resolve()
            if (root / "hyops").exists() and (root / "modules").exists():
                return root
    except Exception:
        pass

    return None


def resolve_module_root(value: str | None = None) -> Path:
    raw = str(value or "modules").strip() or "modules"
    p = Path(raw).expanduser()
    if p.is_absolute():
        return p.resolve()

    core_root = discover_core_root()
    if core_root is not None and raw == "modules":
        core_candidate = (core_root / p).resolve()
        if core_candidate.exists():
            return core_candidate

    cwd_candidate = (Path.cwd() / p).resolve()
    if cwd_candidate.exists():
        return cwd_candidate

    if core_root is not None:
        core_candidate = (core_root / p).resolve()
        if core_candidate.exists():
            return core_candidate

    return cwd_candidate


def resolve_blueprints_root(value: str | None = None) -> Path:
    raw = str(value or "blueprints").strip() or "blueprints"
    p = Path(raw).expanduser()
    if p.is_absolute():
        return p.resolve()

    core_root = discover_core_root()
    if core_root is not None and raw == "blueprints":
        core_candidate = (core_root / p).resolve()
        if core_candidate.exists():
            return core_candidate

    cwd_candidate = (Path.cwd() / p).resolve()
    if cwd_candidate.exists():
        return cwd_candidate

    if core_root is not None:
        core_candidate = (core_root / p).resolve()
        if core_candidate.exists():
            return core_candidate

    return cwd_candidate


def resolve_input_path(value: str | None = None) -> Path | None:
    if not value:
        return None
    raw = str(value).strip()
    if not raw:
        return None

    # Expand env tokens when they are passed literally (for example via single
    # quotes) so commands can use '$HYOPS_CORE_ROOT/...'.
    raw = os.path.expandvars(raw)

    p = Path(raw).expanduser()
    if p.is_absolute():
        resolved = p.resolve()
        if resolved.exists():
            return resolved

        # Operator typo-resilience: if shell expanded an unset $HYOPS_CORE_ROOT
        # token, "$HYOPS_CORE_ROOT/modules/..." commonly degrades to
        # "/modules/...". Recover by rebasing onto discovered core root.
        parts = resolved.parts
        if len(parts) >= 3 and parts[1] in {"modules", "blueprints"}:
            core_root = discover_core_root()
            if core_root is not None:
                rebased = (core_root / Path(*parts[1:])).resolve()
                if rebased.exists():
                    return rebased
        return resolved

    cwd_candidate = (Path.cwd() / p).resolve()
    if cwd_candidate.exists():
        return cwd_candidate

    core_root = discover_core_root()
    if core_root is not None:
        core_candidate = (core_root / p).resolve()
        if core_candidate.exists():
            return core_candidate

    return cwd_candidate


__all__ = [
    "discover_core_root",
    "resolve_module_root",
    "resolve_blueprints_root",
    "resolve_input_path",
]
