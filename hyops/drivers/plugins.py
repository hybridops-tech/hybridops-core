"""
purpose: Discover and register driver plugins (entrypoints).
Architecture Decision: ADR-N/A (driver plugins)
maintainer: HybridOps.Studio
"""

from __future__ import annotations

import os

from hyops.drivers.registry import DriverRegistry


def _plugins_disabled() -> bool:
    v = os.environ.get("HYOPS_NO_PLUGINS", "").strip().lower()
    return v in {"1", "true", "yes"}


def register_plugins(registry: DriverRegistry) -> None:
    if _plugins_disabled():
        return

    from importlib.metadata import entry_points

    group = "hyops.drivers"
    eps = list(entry_points().select(group=group))
    eps.sort(key=lambda ep: ep.name)

    for ep in eps:
        hook = ep.load()
        if not callable(hook):
            raise TypeError(f"driver plugin entrypoint not callable: group={group} name={ep.name}")

        try:
            hook(registry)
        except Exception as e:
            raise RuntimeError(f"driver plugin hook failed: group={group} name={ep.name}") from e