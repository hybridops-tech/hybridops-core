"""Subprocess runner.

purpose: Run external tools with capture, timeouts, and consistent result envelopes.
maintainer: HybridOps.Tech
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
from hyops.runtime.progress import ProgressDisplay, concise_enabled
from hyops.runtime.state import write_json_atomic


@dataclass(frozen=True)
class ProcResult:
    argv: list[str]
    cwd: str | None
    rc: int
    duration_ms: int
    stdout: str
    stderr: str


def _start_error_result(
    argv: Sequence[str], cwd: str | None, start: float, error: OSError
) -> ProcResult:
    command = str(argv[0]) if argv else "command"
    if isinstance(error, FileNotFoundError):
        rc = 127
        stderr = f"command not found: {command}\n"
    else:
        rc = 126
        stderr = f"unable to start command '{command}': {error}\n"
    return ProcResult(
        argv=list(argv),
        cwd=cwd,
        rc=rc,
        duration_ms=int((time.time() - start) * 1000),
        stdout="",
        stderr=stderr,
    )


def run(
    argv: Sequence[str],
    cwd: str | None = None,
    env: Mapping[str, str] | None = None,
    timeout_s: int | None = None,
) -> ProcResult:
    start = time.time()
    try:
        p = subprocess.run(
            list(argv),
            cwd=cwd,
            env=dict(env) if env else None,
            text=True,
            capture_output=True,
            timeout=timeout_s,
            check=False,
        )
    except OSError as error:
        return _start_error_result(argv, cwd, start, error)
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
    progress: bool = True,
) -> ProcResult:
    r = _run_with_delayed_progress(
        argv,
        label=label,
        cwd=cwd,
        env=env,
        timeout_s=timeout_s,
        progress=progress,
    )

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


def _progress_label(label: str) -> str:
    normalized = " ".join(label.replace("_", " ").replace("-", " ").split())
    public_labels = {
        "ansible apply": "configuration",
        "ansible destroy": "configuration teardown",
        "ansible plan": "configuration plan",
        "ansible validate": "configuration validation",
        "terragrunt init": "infrastructure preparation",
        "terragrunt apply": "infrastructure",
        "terragrunt destroy": "infrastructure teardown",
        "terragrunt plan": "infrastructure plan",
        "terragrunt output": "infrastructure state",
        "packer init": "image preparation",
        "packer validate": "image validation",
        "packer build": "image build",
    }
    return public_labels.get(normalized, normalized)


def _run_with_delayed_progress(
    argv: Sequence[str],
    *,
    label: str,
    cwd: str | None,
    env: Mapping[str, str] | None,
    timeout_s: int | None,
    progress: bool = True,
) -> ProcResult:
    """Show progress for a captured command only when it outlasts a quick probe."""

    enabled = (
        progress
        and concise_enabled()
        and str(os.getenv("HYOPS_PROGRESS_CHILD") or "").strip() != "1"
    )
    if not enabled:
        return run(argv, cwd=cwd, env=env, timeout_s=timeout_s)

    display = ProgressDisplay(enabled=True)
    key = f"proc:{label}"
    display_label = _progress_label(label)
    state_lock = threading.Lock()
    state = {"complete": False, "started": False}

    def begin() -> None:
        with state_lock:
            if state["complete"]:
                return
            display.start(key, display_label, plain=f"operation={label} status=running")
            state["started"] = True

    timer = threading.Timer(1.0, begin)
    timer.daemon = True
    timer.start()
    result: ProcResult | None = None
    error: BaseException | None = None
    try:
        result = run(argv, cwd=cwd, env=env, timeout_s=timeout_s)
    except BaseException as exc:
        error = exc
    finally:
        with state_lock:
            state["complete"] = True
            started = state["started"]
        timer.cancel()

    if started:
        succeeded = error is None and result is not None and result.rc == 0
        display.finish(
            key,
            display_label,
            "ok" if succeeded else "failed",
            plain=f"operation={label} status={'ok' if succeeded else 'failed'}",
        )
    if error is not None:
        raise error
    assert result is not None
    return result


def run_interactive(
    argv: Sequence[str],
    cwd: str | None = None,
    env: Mapping[str, str] | None = None,
    timeout_s: int | None = None,
) -> ProcResult:
    start = time.time()
    try:
        p = subprocess.run(
            list(argv),
            cwd=cwd,
            env=dict(env) if env else None,
            text=True,
            timeout=timeout_s,
            check=False,
        )
    except OSError as error:
        return _start_error_result(argv, cwd, start, error)
    dur = int((time.time() - start) * 1000)
    return ProcResult(
        argv=list(argv),
        cwd=cwd,
        rc=int(p.returncode),
        duration_ms=dur,
        stdout="",
        stderr="",
    )


def run_capture_interactive(
    argv: Sequence[str],
    evidence_dir: Path,
    label: str,
    cwd: str | None = None,
    env: Mapping[str, str] | None = None,
    timeout_s: int | None = None,
    redact: bool = True,
) -> ProcResult:
    evidence_dir.mkdir(parents=True, exist_ok=True)
    note = "interactive output streamed directly to terminal; stdout/stderr not captured\n"
    (evidence_dir / f"{label}.stdout.txt").write_text(note, encoding="utf-8")
    (evidence_dir / f"{label}.stderr.txt").write_text(note, encoding="utf-8")
    r = run_interactive(argv, cwd=cwd, env=env, timeout_s=timeout_s)
    _write_result_envelope(evidence_dir, label, r, redact=redact)
    return r


def run_capture_stream(
    argv: Sequence[str],
    evidence_dir: Path,
    label: str,
    display_label: str | None = None,
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
    stream_progress = ProgressDisplay(
        enabled=(
            concise_enabled()
            and str(os.getenv("HYOPS_PROGRESS_CHILD") or "").strip() != "1"
        )
    )
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

    try:
        p = subprocess.Popen(
            list(argv),
            cwd=cwd,
            env=dict(env) if env else None,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            bufsize=1,
        )
    except OSError as error:
        result = _start_error_result(argv, cwd, start, error)
        message = redact_text(result.stderr) if redact else result.stderr
        err_path.write_text(message, encoding="utf-8")
        if tee_f:
            try:
                tee_f.write(message)
                tee_f.write(f"[hyops] {label} end rc={result.rc}\n")
                tee_f.close()
            except Exception:
                pass
        _write_result_envelope(evidence_dir, label, result, redact=redact)
        return result
    if stream_progress.enabled:
        progress_label = _progress_label(display_label or label)
        stream_progress.start(
            label,
            progress_label,
            plain=f"operation={progress_label} status=running",
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

    def heartbeat() -> None:
        if interval <= 0:
            return
        if verbose_terminal:
            return
        if stream_progress.enabled:
            return
        if str(os.getenv("HYOPS_PROGRESS_CHILD") or "").strip() == "1":
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
    if stream_progress.enabled:
        progress_label = _progress_label(display_label or label)
        stream_progress.finish(
            label,
            progress_label,
            "cancelled" if interrupted else ("ok" if rc == 0 else "failed"),
            plain=(
                f"operation={progress_label} "
                f"status={'cancelled' if interrupted else ('ok' if rc == 0 else 'failed')}"
            ),
        )
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
    r = _run_with_delayed_progress(
        argv,
        label=label,
        cwd=cwd,
        env=env,
        timeout_s=timeout_s,
    )
    evidence_dir.mkdir(parents=True, exist_ok=True)
    _write_result_envelope(evidence_dir, label, r)
    return r
