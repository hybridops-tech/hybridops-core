"""Process execution helpers for the Ansible config driver."""

from __future__ import annotations

from pathlib import Path

from hyops.runtime.proc import ProcResult, run_capture_stream


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
) -> ProcResult:
    attempts = max(1, int(retries) + 1)
    last: ProcResult | None = None
    log_path = (evidence_dir / "ansible.log").resolve()
    for attempt in range(1, attempts + 1):
        attempt_label = label if attempt == 1 else f"{label}.retry{attempt - 1}"
        last = run_capture_stream(
            argv,
            cwd=cwd,
            env=env,
            evidence_dir=evidence_dir,
            label=attempt_label,
            timeout_s=timeout_s,
            redact=redact,
            tee_path=log_path,
        )
        if int(last.rc) == 0:
            return last
    if last is None:
        raise RuntimeError("internal error: no command attempt was executed")
    return last
