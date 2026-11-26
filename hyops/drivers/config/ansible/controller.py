"""Controller readiness for the configuration driver."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from .runtime_env import ensure_hybridops_collections_available


def check_controller(request: dict[str, Any]) -> str:
    raw_env = request.get("env")
    env = {
        str(key): str(value)
        for key, value in (raw_env.items() if isinstance(raw_env, dict) else [])
    }
    if str(env.get("ANSIBLE_COLLECTIONS_PATH") or "").strip():
        return ensure_hybridops_collections_available(env)

    runtime_root = Path(
        str(request.get("runtime_root") or Path.home() / ".hybridops")
    ).expanduser()
    candidates = [
        runtime_root / "state" / "ansible" / "galaxy_collections",
        runtime_root / "state" / "ansible" / "collections",
        Path.home() / ".hybridops" / "state" / "ansible" / "galaxy_collections",
        Path.home() / ".hybridops" / "state" / "ansible" / "collections",
        Path.home() / ".ansible" / "collections",
        Path("/usr/share/ansible/collections"),
    ]
    env["ANSIBLE_COLLECTIONS_PATH"] = os.pathsep.join(
        str(path) for path in candidates if path.is_dir()
    )
    return ensure_hybridops_collections_available(env)
