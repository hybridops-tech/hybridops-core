"""Subprocess runner.

purpose: Run external tools with capture, timeouts, and consistent result envelopes.
Architecture Decision: ADR-N/A (proc runner)
maintainer: HybridOps.Studio
"""

from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import signal
from typing import Mapping, Sequence
import subprocess
import sys
import threading
import time

from hyops.runtime.redact import redact_text
from hyops.runtime.state import write_json_atomic


@dataclass(frozen=True)
class ProcResult:
    argv: list[str]
    cwd: str | None
    rc: int
    duration_ms: int
    stdout: str
    stderr: str


def run(
    argv: Sequence[str],
    cwd: str | None = None,
    env: Mapping[str, str] | None = None,
    timeout_s: int | None = None,
) -> ProcResult:
    start = time.time()
    p = subprocess.run(
        list(argv),
        cwd=cwd,
        env=dict(env) if env else None,
        text=True,
        capture_output=True,
        timeout=timeout_s,
        check=False,
    )
    dur = int((time.time() - start) * 1000)
    return ProcResult(
        argv=list(argv),
        cwd=cwd,
        rc=int(p.returncode),
        duration_ms=dur,
        stdout=p.stdout or "",
        stderr=p.stderr or "",
    )


def _redacted_argv(argv: Sequence[str]) -> list[str]:
    return [redact_text(str(token)) for token in argv]


def _write_result_envelope(
    evidence_dir: Path,
    label: str,
    r: ProcResult,
    *,
    mode: int = 0o600,
    redact: bool = False,
) -> None:
    write_json_atomic(
        evidence_dir / f"{label}.result.json",
        {
            "argv": _redacted_argv(r.argv) if redact else r.argv,
            "cwd": r.cwd,
            "rc": r.rc,
            "duration_ms": r.duration_ms,
        },
        mode=mode,
    )


def run_capture(
    argv: Sequence[str],
    evidence_dir: Path,
    label: str,
    cwd: str | None = None,
    env: Mapping[str, str] | None = None,
    timeout_s: int | None = None,
    redact: bool = True,
) -> ProcResult:
    r = run(argv, cwd=cwd, env=env, timeout_s=timeout_s)

    out = r.stdout
    err = r.stderr
    if redact:
        out = redact_text(out)
        err = redact_text(err)

    evidence_dir.mkdir(parents=True, exist_ok=True)
    (evidence_dir / f"{label}.stdout.txt").write_text(out, encoding="utf-8")
    (evidence_dir / f"{label}.stderr.txt").write_text(err, encoding="utf-8")
    _write_result_envelope(evidence_dir, label, r, redact=redact)
    return r


def run_capture_stream(
    argv: Sequence[str],
    evidence_dir: Path,
    label: str,
    cwd: str | None = None,
    env: Mapping[str, str] | None = None,
    timeout_s: int | None = None,
    redact: bool = True,
    tee_path: Path | None = None,
    heartbeat_every_s: int | None = None,
) -> ProcResult:
    """Run a subprocess and stream stdout/stderr to evidence files while it runs.

    Use this for long-running commands where operators want to `tail -f` logs in real time.
    Note: this does not return full stdout/stderr in-memory; read evidence files instead.
    Set `HYOPS_VERBOSE=1` (or `hyops --verbose`) to also mirror subprocess output to the terminal.
    """

    start = time.time()
    evidence_dir.mkdir(parents=True, exist_ok=True)

    out_path = evidence_dir / f"{label}.stdout.txt"
    err_path = evidence_dir / f"{label}.stderr.txt"

    # Ensure files exist immediately so users can tail them.
    out_path.write_text("", encoding="utf-8")
    err_path.write_text("", encoding="utf-8")

    tee_f = None
    tee_lock = threading.Lock()
    terminal_lock = threading.Lock()
    heartbeat_stop = threading.Event()
    verbose_terminal = str(os.getenv("HYOPS_VERBOSE") or "").strip().lower() in {"1", "true", "yes", "on"}
    if tee_path is not None:
        try:
            tee_path.parent.mkdir(parents=True, exist_ok=True)
            tee_f = tee_path.open("a", encoding="utf-8", errors="replace")
            safe_argv = _redacted_argv(argv) if redact else list(argv)
            tee_f.write(f"\n[hyops] {label} start argv={safe_argv!r}\n")
            tee_f.flush()
        except Exception:
            tee_f = None

    def pump(src, dst: Path, stream: str) -> None:
        try:
            with dst.open("a", encoding="utf-8", errors="replace") as f:
                for line in src:
                    token = redact_text(line) if redact else line
                    f.write(token)
                    f.flush()
                    if tee_f:
                        with tee_lock:
                            tee_f.write(token)
                            tee_f.flush()
                    if verbose_terminal:
                        target = sys.stdout if stream == "stdout" else sys.stderr
                        if target is not None:
                            with terminal_lock:
                                target.write(token)
                                target.flush()
        except Exception:
            # Best-effort log capture; never raise from pump threads.
            pass
        finally:
            try:
                src.close()
            except Exception:
                pass

    p = subprocess.Popen(
        list(argv),
        cwd=cwd,
        env=dict(env) if env else None,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        bufsize=1,
    )
    assert p.stdout is not None
    assert p.stderr is not None

    t_out = threading.Thread(target=pump, args=(p.stdout, out_path, "stdout"), daemon=True)
    t_err = threading.Thread(target=pump, args=(p.stderr, err_path, "stderr"), daemon=True)
    t_out.start()
    t_err.start()

    interval = heartbeat_every_s
    if interval is None:
        raw = str(os.getenv("HYOPS_PROGRESS_INTERVAL_S") or "").strip()
        if raw:
            try:
                interval = int(raw)
            except Exception:
                interval = 45
        else:
            interval = 45
    interval = int(interval) if interval is not None else 0

    heartbeat_thread: threading.Thread | None = None
    progress_path = tee_path if tee_path is not None else out_path

    def latest_progress_line(path: Path) -> str:
        try:
            if not path.exists() or not path.is_file():
                return ""
            with path.open("rb") as f:
                f.seek(0, os.SEEK_END)
                size = f.tell()
                if size <= 0:
                    return ""
                window = min(size, 4096)
                f.seek(-window, os.SEEK_END)
                chunk = f.read(window).decode("utf-8", errors="replace")
        except Exception:
            return ""
        for line in reversed(chunk.splitlines()):
            cleaned = line.strip()
            if cleaned:
                return cleaned
        return ""

    if sys.stdout and sys.stdout.isatty():
        print(
            f"[hyops] {label}: watch logs: tail -f {progress_path}",
            file=sys.stdout,
            flush=True,
        )

    def heartbeat() -> None:
        if interval <= 0:
            return
        if verbose_terminal:
            return
        if not sys.stdout or not sys.stdout.isatty():
            return
        while not heartbeat_stop.wait(interval):
            elapsed = int(max(0, time.time() - start))
            latest = latest_progress_line(progress_path)
            suffix = f" latest={latest}" if latest else ""
            print(
                f"[hyops] {label}: still running ({elapsed}s) logs={progress_path}{suffix}",
                file=sys.stdout,
                flush=True,
            )

    if interval > 0:
        heartbeat_thread = threading.Thread(target=heartbeat, daemon=True)
        heartbeat_thread.start()

    rc = 1
    interrupted = False
    try:
        rc = int(p.wait(timeout=timeout_s))
    except KeyboardInterrupt:
        interrupted = True
        try:
            if p.poll() is None:
                try:
                    p.send_signal(signal.SIGINT)
                except Exception:
                    try:
                        p.terminate()
                    except Exception:
                        pass
                try:
                    rc = int(p.wait(timeout=15))
                except subprocess.TimeoutExpired:
                    try:
                        p.kill()
                    except Exception:
                        pass
                    rc = int(p.wait(timeout=10))
            elif p.returncode is not None:
                rc = int(p.returncode)
        except Exception:
            rc = 130
    except subprocess.TimeoutExpired:
        try:
            p.kill()
        except Exception:
            pass
        rc = int(p.wait(timeout=10))
    finally:
        heartbeat_stop.set()
        t_out.join(timeout=2)
        t_err.join(timeout=2)
        if heartbeat_thread is not None:
            heartbeat_thread.join(timeout=1)
        if tee_f:
            try:
                tee_f.write(f"[hyops] {label} end rc={rc}\n")
                tee_f.flush()
                tee_f.close()
            except Exception:
                pass

    dur = int((time.time() - start) * 1000)
    r = ProcResult(
        argv=list(argv),
        cwd=cwd,
        rc=rc,
        duration_ms=dur,
        stdout="",
        stderr="",
    )
    _write_result_envelope(evidence_dir, label, r, redact=redact)
    if interrupted:
        raise KeyboardInterrupt
    return r


def run_capture_sensitive(
    argv: Sequence[str],
    evidence_dir: Path,
    label: str,
    cwd: str | None = None,
    env: Mapping[str, str] | None = None,
    timeout_s: int | None = None,
) -> ProcResult:
    """Capture only the result envelope.

    For commands that may emit secrets, do not persist stdout/stderr to disk.
    """
    r = run(argv, cwd=cwd, env=env, timeout_s=timeout_s)
    evidence_dir.mkdir(parents=True, exist_ok=True)
    _write_result_envelope(evidence_dir, label, r)
    return r
