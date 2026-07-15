"""
purpose: Enforce the published Core support boundary for mutating operations.
maintainer: HybridOps.Tech
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests

from hyops import __version__
from hyops.runtime.paths import resolve_runtime_paths
from hyops.update.checker import DEFAULT_INTERVAL_SECONDS, _version_tuple


DEFAULT_POLICY_URL = (
    "https://raw.githubusercontent.com/hybridops-tech/hybridops-core/main/pkg/support-policy.json"
)


@dataclass(frozen=True)
class PolicyDecision:
    state: str
    installed: str
    minimum: str | None = None
    enforce_after: str | None = None
    cached: bool = False

    @property
    def blocked(self) -> bool:
        return self.state == "blocked"


def _policy_cache_path(root: str | None) -> Path:
    return resolve_runtime_paths(root).meta_dir / "core-support-policy.json"


def _read_policy(path: Path) -> dict[str, Any] | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return None
    return data if isinstance(data, dict) else None


def _write_policy(path: Path, policy: dict[str, Any]) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(".tmp")
        temporary.write_text(json.dumps(policy, sort_keys=True) + "\n", encoding="utf-8")
        temporary.replace(path)
    except OSError:
        return


def _parse_enforce_after(value: str) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(timezone.utc)


def support_decision(
    *,
    root: str | None = None,
    timeout: float = 2.0,
    now: float | None = None,
) -> PolicyDecision:
    installed = _version_tuple(__version__)
    if installed is None:
        return PolicyDecision(state="development", installed=__version__)

    checked_at = time.time() if now is None else now
    cache_path = _policy_cache_path(root)
    cached_policy = _read_policy(cache_path)
    policy = None
    cached = False
    if cached_policy is not None:
        try:
            age = checked_at - float(cached_policy.get("checked_at", 0))
        except (TypeError, ValueError):
            age = DEFAULT_INTERVAL_SECONDS + 1
        if 0 <= age <= DEFAULT_INTERVAL_SECONDS:
            policy = cached_policy
            cached = True

    if policy is None:
        endpoint = os.environ.get("HYOPS_UPDATE_POLICY_URL", DEFAULT_POLICY_URL).strip()
        try:
            response = requests.get(endpoint, timeout=timeout)
            response.raise_for_status()
            remote = response.json()
            if not isinstance(remote, dict):
                raise ValueError("support policy must be a JSON object")
            policy = dict(remote)
            policy["checked_at"] = checked_at
            _write_policy(cache_path, policy)
        except (requests.RequestException, ValueError, TypeError):
            if cached_policy is None:
                return PolicyDecision(state="unavailable", installed=__version__)
            policy = cached_policy
            cached = True

    if policy.get("schema_version") != 1:
        return PolicyDecision(state="invalid", installed=__version__, cached=cached)
    minimum_text = str(policy.get("minimum_supported_version") or "")
    minimum = _version_tuple(minimum_text)
    enforce_text = str(policy.get("enforce_after") or "")
    enforce_after = _parse_enforce_after(enforce_text)
    if minimum is None or enforce_after is None:
        return PolicyDecision(state="invalid", installed=__version__, cached=cached)
    if installed >= minimum:
        state = "supported"
    elif datetime.fromtimestamp(checked_at, tz=timezone.utc) < enforce_after:
        state = "grace"
    else:
        state = "blocked"
    return PolicyDecision(
        state=state,
        installed=__version__,
        minimum=minimum_text,
        enforce_after=enforce_text,
        cached=cached,
    )


def command_requires_supported_release(ns: Any) -> bool:
    command = str(getattr(ns, "cmd", "") or "")
    if command in {"apply", "deploy", "import", "rebuild", "init"}:
        return True
    return command == "blueprint" and getattr(ns, "blueprint_cmd", "") in {
        "deploy",
        "rebuild",
    } and bool(getattr(ns, "execute", False))
