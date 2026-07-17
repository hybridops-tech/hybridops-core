"""Runtime storage checks and operator-facing failure guidance."""

from __future__ import annotations

import errno
import os
from pathlib import Path


_STORAGE_ERRNOS = {errno.EROFS, errno.EIO}


def is_wsl() -> bool:
    try:
        release = Path("/proc/sys/kernel/osrelease").read_text(encoding="utf-8")
    except OSError:
        return False
    return "microsoft" in release.lower()


def runtime_storage_guidance() -> str:
    if is_wsl():
        return (
            "Close HybridOps.Core, run `wsl --shutdown` in Windows PowerShell, "
            "reopen HybridOps.Core and rerun preflight. If the error returns, follow "
            "the Microsoft WSL disk-repair procedure: "
            "https://learn.microsoft.com/windows/wsl/disk-space#how-to-repair-a-vhd-mounting-error"
        )
    return "Check that the runtime filesystem is writable and has free space, then rerun preflight."


def format_runtime_storage_error(error: BaseException) -> str:
    if isinstance(error, OSError) and error.errno == errno.ENOSPC:
        return "local runtime storage is full. Free disk space, then rerun preflight."
    if isinstance(error, OSError) and error.errno in _STORAGE_ERRNOS:
        return f"local runtime storage is unavailable. {runtime_storage_guidance()}"
    detail = str(error)
    if "Read-only file system" in detail or "Input/output error" in detail:
        return f"local runtime storage is unavailable. {runtime_storage_guidance()}"
    return detail


def check_runtime_writable(path: Path) -> tuple[bool, str]:
    probe = path / f".hyops-write-probe-{os.getpid()}"
    descriptor: int | None = None
    try:
        descriptor = os.open(probe, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        os.write(descriptor, b"ok\n")
        os.fsync(descriptor)
        os.close(descriptor)
        descriptor = None
        probe.unlink()
        return True, str(path)
    except OSError as error:
        if descriptor is not None:
            try:
                os.close(descriptor)
            except OSError:
                pass
        try:
            probe.unlink(missing_ok=True)
        except OSError:
            pass
        return False, format_runtime_storage_error(error)


def require_runtime_writable(path: Path) -> None:
    writable, detail = check_runtime_writable(path)
    if not writable:
        raise OSError(detail)
