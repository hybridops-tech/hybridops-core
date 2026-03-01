"""Terragrunt driver runtime environment helpers (internal)."""

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path
from typing import Any


def _resolve_hyops_executable() -> str:
    """Resolve the current hyops executable path for child hooks/processes."""
    argv0 = str(getattr(sys, "argv", [""])[:1][0] or "").strip()
    if argv0:
        if "/" in argv0:
            try:
                return str(Path(argv0).expanduser().resolve())
            except Exception:
                pass
        resolved = shutil.which(argv0)
        if resolved:
            return str(Path(resolved).expanduser().resolve())
    resolved = shutil.which("hyops")
    return str(Path(resolved).expanduser().resolve()) if resolved else "hyops"


def build_runtime_env(*, runtime_root: Path, runtime: dict[str, Any]) -> tuple[dict[str, str], str]:
    """Build and normalize runtime environment for terragrunt execution."""
    env = os.environ.copy()
    env["HYOPS_RUNTIME_ROOT"] = str(runtime_root)

    env_name = str(runtime.get("env") or "").strip()
    if env_name and "HYOPS_ENV" not in env:
        env["HYOPS_ENV"] = env_name
    if not str(env.get("HYOPS_EXECUTABLE") or "").strip():
        env["HYOPS_EXECUTABLE"] = _resolve_hyops_executable()

    # Terraform uses /tmp for provider install staging. Keep runs reliable by
    # forcing temp + plugin cache under the runtime root when not overridden.
    runtime_tmp = runtime_root / "tmp"
    runtime_tf_cache = runtime_root / "cache" / "terraform" / "plugins"
    try:
        runtime_tmp.mkdir(parents=True, exist_ok=True)
        runtime_tf_cache.mkdir(parents=True, exist_ok=True)
    except Exception:
        # Never block execution on cache/temp dir creation; Terraform will fall
        # back to /tmp and may fail if the system is full.
        pass

    if not str(env.get("TMPDIR") or "").strip():
        env["TMPDIR"] = str(runtime_tmp)
    if not str(env.get("TF_PLUGIN_CACHE_DIR") or "").strip():
        env["TF_PLUGIN_CACHE_DIR"] = str(runtime_tf_cache)

    return env, env_name
