"""
purpose: Resolve a pack stack directory from driver_ref + pack_id.
maintainer: HybridOps.Tech
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable
import os


class PackResolveError(RuntimeError):
    pass


class PackNotFoundError(PackResolveError):
    pass


class PackInvalidError(PackResolveError):
    pass


@dataclass(frozen=True)
class PackResolved:
    packs_root: Path
    driver_ref: str
    pack_id: str
    stack_dir: Path


def _sanitize_rel_path(p: str) -> str:
    s = (p or "").strip().strip("/")
    if not s:
        raise PackInvalidError("pack_id is required")
    if "\x00" in s:
        raise PackInvalidError("pack_id contains invalid characters")

    parts = [x for x in s.split("/") if x and x not in (".", "..")]
    cleaned = "/".join(parts)

    if not cleaned or cleaned.startswith(("/", "\\")) or ":" in cleaned:
        raise PackInvalidError("pack_id must be a relative path")
    return cleaned


def _find_packs_root_from_here(start: Path) -> Path | None:
    cur = start.resolve()
    for parent in [cur, *cur.parents]:
        candidate = parent / "packs"
        if candidate.is_dir():
            return candidate.resolve()
    return None


def resolve_packs_root(packs_root: str | None = None) -> Path:
    if packs_root:
        p = Path(packs_root).expanduser().resolve()
        if not p.is_dir():
            raise PackNotFoundError(f"packs root not found: {p}")
        return p

    env = os.environ.get("HYOPS_PACKS_ROOT", "").strip()
    if env:
        p = Path(env).expanduser().resolve()
        if not p.is_dir():
            raise PackNotFoundError(f"packs root not found (HYOPS_PACKS_ROOT): {p}")
        return p

    # Installed wrapper exports HYOPS_CORE_ROOT; prefer its co-located packs tree
    # so global `hyops` works outside the source checkout.
    core_root = os.environ.get("HYOPS_CORE_ROOT", "").strip()
    if core_root:
        core_packs = (Path(core_root).expanduser().resolve() / "packs").resolve()
        if core_packs.is_dir():
            return core_packs

    discovered = _find_packs_root_from_here(Path(__file__))
    if discovered:
        return discovered

    raise PackNotFoundError("packs root not found; set HYOPS_PACKS_ROOT to an existing packs directory")


def resolve_pack_stack(
    *,
    driver_ref: str,
    pack_id: str,
    packs_root: str | None = None,
    require_stack_files: Iterable[str] = (),
) -> PackResolved:
    dref = (driver_ref or "").strip().strip("/")
    if not dref:
        raise PackInvalidError("driver_ref is required")

    pid = _sanitize_rel_path(pack_id)

    root = resolve_packs_root(packs_root)
    stack_dir = (root / dref / pid / "stack").resolve()

    try:
        stack_dir.relative_to(root)
    except Exception as e:
        raise PackInvalidError("pack resolution escaped packs_root") from e

    if not stack_dir.is_dir():
        raise PackNotFoundError(f"pack stack not found: {stack_dir}")

    missing = [f for f in require_stack_files if not (stack_dir / f).exists()]
    if missing:
        raise PackInvalidError(f"pack stack missing required files: {', '.join(missing)}")

    return PackResolved(packs_root=root, driver_ref=dref, pack_id=pid, stack_dir=stack_dir)
