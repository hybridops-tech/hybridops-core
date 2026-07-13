"""Open operator URLs on the host desktop.

purpose: Bridge browser launch behaviour across Linux, macOS, and Windows WSL.
maintainer: HybridOps.Tech
"""

from __future__ import annotations

import os
import platform
import shutil
import subprocess
import webbrowser
from collections.abc import Mapping


def is_windows_wsl(
    *,
    environ: Mapping[str, str] | None = None,
    kernel_release: str | None = None,
) -> bool:
    env = os.environ if environ is None else environ
    if platform.system() != "Linux":
        return False
    if env.get("WSL_DISTRO_NAME") or env.get("WSL_INTEROP"):
        return True
    release = platform.release() if kernel_release is None else kernel_release
    return "microsoft" in release.lower()


def open_operator_url(url: str, *, new: int = 0) -> bool:
    """Open a URL in the desktop browser, including the Windows host from WSL."""

    if is_windows_wsl():
        for command in ("wslview", "explorer.exe"):
            executable = shutil.which(command)
            if not executable:
                continue
            try:
                subprocess.Popen(
                    [executable, url],
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    start_new_session=True,
                )
                return True
            except OSError:
                continue
    return bool(webbrowser.open(url, new=new))
