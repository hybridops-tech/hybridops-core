"""Discover optional authority providers through Python entry points."""

from __future__ import annotations

import os
from typing import Any

from .models import AuthorityProviderIdentity
from .registry import AuthorityProviderRegistry

ENTRY_POINT_GROUP = "hyops.authority_providers"


class _PluginRegistry:
    def __init__(
        self,
        registry: AuthorityProviderRegistry,
        identity: AuthorityProviderIdentity,
    ) -> None:
        self._registry = registry
        self._identity = identity
        self._registered = 0

    @property
    def registered(self) -> int:
        return self._registered

    def register(self, provider: Any) -> None:
        self._registry.register(provider, identity=self._identity)
        self._registered += 1

    def resolve(self, name: str):
        return self._registry.resolve(name)

    def names(self) -> tuple[str, ...]:
        return self._registry.names()


def _plugins_disabled() -> bool:
    value = os.environ.get("HYOPS_NO_PLUGINS", "").strip().lower()
    return value in {"1", "true", "yes"}


def register_plugins(registry: AuthorityProviderRegistry) -> None:
    if _plugins_disabled():
        registry.mark_discovery_complete()
        return

    entry_point_name = "<discovery>"
    try:
        from importlib.metadata import entry_points

        raw_entry_points = entry_points()
        if hasattr(raw_entry_points, "select"):
            providers = list(raw_entry_points.select(group=ENTRY_POINT_GROUP))
        elif isinstance(raw_entry_points, dict):
            providers = list(raw_entry_points.get(ENTRY_POINT_GROUP, ()))
        else:
            providers = [
                item
                for item in raw_entry_points
                if getattr(item, "group", None) == ENTRY_POINT_GROUP
            ]
        providers.sort(key=lambda item: item.name)
        staged = registry.clone()
        for entry_point in providers:
            entry_point_name = entry_point.name
            hook = entry_point.load()
            if not callable(hook):
                raise TypeError(
                    "authority provider entrypoint is not callable: "
                    f"group={ENTRY_POINT_GROUP} name={entry_point.name}"
                )
            distribution = getattr(entry_point, "dist", None)
            metadata = getattr(distribution, "metadata", None)
            distribution_name = ""
            if metadata is not None:
                distribution_name = str(metadata.get("Name") or "").strip()
            distribution_version = str(
                getattr(distribution, "version", "") or ""
            ).strip()
            if not distribution_name or not distribution_version:
                raise ValueError(
                    "authority provider entrypoint lacks distribution identity: "
                    f"group={ENTRY_POINT_GROUP} name={entry_point.name}"
                )
            identity = AuthorityProviderIdentity(
                source="plugin",
                distribution=distribution_name,
                version=distribution_version,
                entry_point=f"{ENTRY_POINT_GROUP}:{entry_point.name}",
            )
            plugin_registry = _PluginRegistry(staged, identity)
            hook(plugin_registry)
            if plugin_registry.registered == 0:
                raise ValueError(
                    "authority provider entrypoint did not register a provider: "
                    f"group={ENTRY_POINT_GROUP} name={entry_point.name}"
                )
        staged.mark_discovery_complete()
        registry.replace_from(staged)
    except Exception as exc:
        detail = (
            "authority provider hook failed: "
            f"group={ENTRY_POINT_GROUP} name={entry_point_name}: {exc}"
        )
        registry.record_discovery_error(detail)
        raise RuntimeError(detail) from exc
