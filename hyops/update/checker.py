"""
purpose: Check the installed Core version against the latest published release.
maintainer: HybridOps.Tech
"""

from __future__ import annotations

import json
import os
import re
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import requests

from hyops import __version__
from hyops.runtime.paths import resolve_runtime_paths


DEFAULT_RELEASE_URL = "https://api.github.com/repos/hybridops-tech/hybridops-core/releases/latest"
DEFAULT_INTERVAL_SECONDS = 24 * 60 * 60


@dataclass(frozen=True)
class UpdateStatus:
    state: str
    installed: str
    latest: str | None = None
    release_url: str | None = None
    detail: str | None = None
    cached: bool = False


def _version_tuple(value: str) -> tuple[int, int, int] | None:
    match = re.fullmatch(r"v?(\d+)\.(\d+)\.(\d+)", value.strip())
    if not match:
        return None
    return tuple(int(part) for part in match.groups())


def _cache_path(root: str | None = None) -> Path:
    return resolve_runtime_paths(root).meta_dir / "core-update.json"


def _read_cache(path: Path, now: float, max_age: int) -> dict[str, Any] | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        checked_at = float(data.get("checked_at", 0))
    except (OSError, ValueError, TypeError):
        return None
    if checked_at <= 0 or now - checked_at > max_age:
        return None
    return data


def _write_cache(path: Path, data: dict[str, Any]) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(".tmp")
        temporary.write_text(json.dumps(data, sort_keys=True) + "\n", encoding="utf-8")
        temporary.replace(path)
    except OSError:
        return


def check_for_update(
    *,
    root: str | None = None,
    use_cache: bool = True,
    timeout: float = 2.0,
    now: float | None = None,
) -> UpdateStatus:
    installed_tuple = _version_tuple(__version__)
    if installed_tuple is None:
        return UpdateStatus(state="development", installed=__version__)

    checked_at = time.time() if now is None else now
    try:
        interval = max(0, int(os.environ.get("HYOPS_UPDATE_CHECK_INTERVAL", DEFAULT_INTERVAL_SECONDS)))
    except ValueError:
        interval = DEFAULT_INTERVAL_SECONDS
    cache_path = _cache_path(root)
    payload = _read_cache(cache_path, checked_at, interval) if use_cache else None
    cached = payload is not None

    if payload is None:
        endpoint = os.environ.get("HYOPS_UPDATE_RELEASE_URL", DEFAULT_RELEASE_URL).strip()
        try:
            response = requests.get(
                endpoint,
                headers={"Accept": "application/vnd.github+json"},
                timeout=timeout,
            )
            response.raise_for_status()
            remote = response.json()
            payload = {
                "checked_at": checked_at,
                "tag_name": str(remote.get("tag_name") or ""),
                "html_url": str(remote.get("html_url") or ""),
            }
            _write_cache(cache_path, payload)
        except (requests.RequestException, ValueError, TypeError) as exc:
            return UpdateStatus(
                state="offline",
                installed=__version__,
                detail=str(exc),
            )

    latest = str(payload.get("tag_name") or "").removeprefix("v")
    latest_tuple = _version_tuple(latest)
    if latest_tuple is None:
        return UpdateStatus(
            state="unavailable",
            installed=__version__,
            detail="latest release did not contain a numeric version",
            cached=cached,
        )

    unsupported = latest_tuple[0] > installed_tuple[0] or (
        installed_tuple[0] == 0 and latest_tuple[1] > installed_tuple[1]
    )
    if unsupported:
        state = "unsupported"
    else:
        state = "update_available" if latest_tuple > installed_tuple else "current"
    return UpdateStatus(
        state=state,
        installed=__version__,
        latest=latest,
        release_url=str(payload.get("html_url") or "") or None,
        cached=cached,
    )


def automatic_checks_enabled() -> bool:
    return os.environ.get("HYOPS_UPDATE_CHECK", "1").strip().lower() not in {
        "0",
        "false",
        "no",
        "off",
    }


def maybe_print_update_notice(command: str | None) -> None:
    if command in {None, "update", "destroy"}:
        return
    if not automatic_checks_enabled() or not sys.stderr.isatty():
        return
    try:
        status = check_for_update()
    except Exception:
        return
    if status.state not in {"update_available", "unsupported"}:
        return
    if status.state == "unsupported":
        message = (
            f"Core release {status.installed} is outside the current release line "
            f"({status.latest}). Run: hyops update check"
        )
    else:
        message = (
            f"Update available: HybridOps.Core {status.latest} "
            f"(installed {status.installed}). Run: hyops update check"
        )
    print(message, file=sys.stderr)
