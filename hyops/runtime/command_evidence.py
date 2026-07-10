"""Secure, streaming evidence capture for operator-facing commands."""

from __future__ import annotations

from contextlib import AbstractContextManager
from datetime import datetime, timezone
import json
from pathlib import Path
import platform
import subprocess
import sys
from typing import IO, Mapping, Sequence

from hyops.runtime.evidence import init_evidence_dir, new_run_id
from hyops.runtime.redact import redact_text


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def command_evidence_dir(logs_dir: Path, command: str, scope: str = "") -> Path:
    root = logs_dir / command
    if scope:
        root /= scope
    evidence_dir = init_evidence_dir(root, new_run_id(command.replace("-", "_")))
    evidence_dir.chmod(0o700)
    return evidence_dir


def write_result(
    evidence_dir: Path,
    *,
    command: str,
    argv: Sequence[str],
    started_at: str,
    exit_code: int,
) -> None:
    payload = {
        "command": command,
        "argv": [redact_text(str(token)) for token in argv],
        "started_at": started_at,
        "finished_at": _utc_now(),
        "exit_code": int(exit_code),
        "status": "ok" if int(exit_code) == 0 else "failed",
        "platform": {
            "system": platform.system(),
            "machine": platform.machine(),
            "python": platform.python_version(),
        },
    }
    path = evidence_dir / "result.json"
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    path.chmod(0o600)


def run_streamed(
    argv: Sequence[str],
    *,
    env: Mapping[str, str],
    evidence_dir: Path,
    command: str,
) -> int:
    started_at = _utc_now()
    output_path = evidence_dir / "output.log"
    with output_path.open("w", encoding="utf-8") as output:
        output_path.chmod(0o600)
        process = subprocess.Popen(
            list(argv),
            env=dict(env),
            stdin=None,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            errors="replace",
            bufsize=1,
        )
        assert process.stdout is not None
        for raw_line in process.stdout:
            safe_line = redact_text(raw_line)
            sys.stdout.write(safe_line)
            sys.stdout.flush()
            output.write(safe_line)
            output.flush()
        exit_code = int(process.wait())
    write_result(
        evidence_dir,
        command=command,
        argv=argv,
        started_at=started_at,
        exit_code=exit_code,
    )
    print(f"run record: {evidence_dir}")
    return exit_code


class _TeeStream:
    def __init__(self, terminal: IO[str], output: IO[str]) -> None:
        self.terminal = terminal
        self.output = output

    def write(self, text: str) -> int:
        safe_text = redact_text(text)
        self.terminal.write(safe_text)
        self.terminal.flush()
        self.output.write(safe_text)
        self.output.flush()
        return len(text)

    def flush(self) -> None:
        self.terminal.flush()
        self.output.flush()

    def isatty(self) -> bool:
        return self.terminal.isatty()

    def fileno(self) -> int:
        return self.terminal.fileno()


class PythonCommandEvidence(AbstractContextManager["PythonCommandEvidence"]):
    def __init__(self, evidence_dir: Path, *, command: str, argv: Sequence[str]) -> None:
        self.evidence_dir = evidence_dir
        self.command = command
        self.argv = list(argv)
        self.started_at = _utc_now()
        self.exit_code = 1
        self._output: IO[str] | None = None
        self._stdout = sys.stdout
        self._stderr = sys.stderr

    def __enter__(self) -> "PythonCommandEvidence":
        path = self.evidence_dir / "output.log"
        self._output = path.open("w", encoding="utf-8")
        path.chmod(0o600)
        sys.stdout = _TeeStream(self._stdout, self._output)  # type: ignore[assignment]
        sys.stderr = _TeeStream(self._stderr, self._output)  # type: ignore[assignment]
        return self

    def __exit__(self, exc_type, exc, traceback) -> bool:
        sys.stdout = self._stdout
        sys.stderr = self._stderr
        if self._output is not None:
            self._output.close()
        if exc_type is not None and self.exit_code == 0:
            self.exit_code = 1
        write_result(
            self.evidence_dir,
            command=self.command,
            argv=self.argv,
            started_at=self.started_at,
            exit_code=self.exit_code,
        )
        print(f"run record: {self.evidence_dir}")
        return False
