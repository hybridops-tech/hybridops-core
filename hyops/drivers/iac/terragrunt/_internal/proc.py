"""Terragrunt driver process helpers (internal)."""

from __future__ import annotations

from pathlib import Path

from hyops.runtime.proc import ProcResult, run_capture, run_capture_stream
from hyops.runtime.redact import redact_text


def _append_tee(
    *,
    tee_path: Path | None,
    label: str,
    argv: list[str],
    r: ProcResult,
    redact: bool,
) -> None:
    if tee_path is None:
        return
    try:
        tee_path.parent.mkdir(parents=True, exist_ok=True)
        with tee_path.open("a", encoding="utf-8", errors="replace") as f:
            f.write(f"\n[hyops] {label} start argv={argv!r}\n")
            out = r.stdout or ""
            err = r.stderr or ""
            if redact:
                out = redact_text(out)
                err = redact_text(err)
            if out:
                f.write(out)
                if not out.endswith("\n"):
                    f.write("\n")
            if err:
                f.write(err)
                if not err.endswith("\n"):
                    f.write("\n")
            f.write(f"[hyops] {label} end rc={int(r.rc)}\n")
    except Exception:
        pass


def run_capture_with_policy(
    *,
    argv: list[str],
    cwd: str,
    env: dict[str, str],
    evidence_dir: Path,
    label: str,
    timeout_s: int | None,
    redact: bool,
    retries: int,
    tee_path: Path | None = None,
    stream: bool = False,
) -> ProcResult:
    attempts = max(1, int(retries) + 1)
    last: ProcResult | None = None
    for attempt in range(1, attempts + 1):
        attempt_label = label if attempt == 1 else f"{label}.retry{attempt - 1}"
        if stream:
            last = run_capture_stream(
                argv,
                cwd=cwd,
                env=env,
                evidence_dir=evidence_dir,
                label=attempt_label,
                timeout_s=timeout_s,
                redact=redact,
                tee_path=tee_path,
            )
        else:
            last = run_capture(
                argv,
                cwd=cwd,
                env=env,
                evidence_dir=evidence_dir,
                label=attempt_label,
                timeout_s=timeout_s,
                redact=redact,
            )
            _append_tee(
                tee_path=tee_path,
                label=attempt_label,
                argv=list(argv),
                r=last,
                redact=redact,
            )
        if int(last.rc) == 0:
            return last
    if last is None:
        raise RuntimeError("internal error: no command attempt was executed")
    return last
