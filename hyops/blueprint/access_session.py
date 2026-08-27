"""Persistent state and locking for time-bounded blueprint access sessions."""

from __future__ import annotations

from contextlib import AbstractContextManager
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import re
import socket
from typing import Any

from hyops.runtime.state import read_json, write_json_atomic


SESSION_SCHEMA_VERSION = 1
SESSION_FINAL_STATES = frozenset(
    {
        "cancelled",
        "completed",
        "interrupted",
        "released",
        "retained-after-failure",
        "stale-generation",
    }
)


class LifecycleBusy(RuntimeError):
    """Raised when another lifecycle operation owns the environment lock."""


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def format_utc(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def parse_utc(value: str) -> datetime:
    text = str(value or "").strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        raise ValueError("session timestamp must include a timezone")
    return parsed.astimezone(timezone.utc)


def _token(value: str) -> str:
    token = re.sub(r"[^A-Za-z0-9_.-]+", "_", str(value)).strip("._")
    return token or "blueprint"


def session_state_path(paths, blueprint_ref: str) -> Path:
    return paths.meta_dir / "access_sessions" / f"{_token(blueprint_ref)}.json"


def session_run_record_path(paths, blueprint_ref: str, session_id: str) -> Path:
    return (
        paths.logs_dir
        / "blueprint"
        / _token(blueprint_ref)
        / _token(session_id)
        / "session.json"
    )


def load_session(paths, blueprint_ref: str) -> dict[str, Any] | None:
    path = session_state_path(paths, blueprint_ref)
    if not path.is_file():
        return None
    record = read_json(path)
    if str(record.get("blueprint_ref") or "") != blueprint_ref:
        raise ValueError(f"session state does not belong to {blueprint_ref}")
    return record


def save_session(paths, record: dict[str, Any], *, now: datetime | None = None) -> Path:
    current = now or utc_now()
    payload = dict(record)
    payload["updated_at"] = format_utc(current)
    blueprint_ref = str(payload.get("blueprint_ref") or "").strip()
    session_id = str(payload.get("session_id") or "").strip()
    if not blueprint_ref or not session_id:
        raise ValueError("session record requires blueprint_ref and session_id")
    state_path = session_state_path(paths, blueprint_ref)
    run_record = session_run_record_path(paths, blueprint_ref, session_id)
    payload["run_record"] = str(run_record)
    write_json_atomic(state_path, payload)
    write_json_atomic(run_record, payload)
    record.clear()
    record.update(payload)
    return run_record


def supervisor_running(record: dict[str, Any]) -> bool:
    supervisor = record.get("supervisor")
    if not isinstance(supervisor, dict):
        return False
    if str(supervisor.get("host") or "") != socket.gethostname():
        return False
    try:
        pid = int(supervisor.get("pid") or 0)
    except (TypeError, ValueError):
        return False
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    return True


def effective_status(
    record: dict[str, Any],
    *,
    now: datetime | None = None,
    supervisor_is_running: bool | None = None,
) -> str:
    status = str(record.get("status") or "unknown")
    if status in SESSION_FINAL_STATES:
        return status
    running = (
        supervisor_running(record)
        if supervisor_is_running is None
        else supervisor_is_running
    )
    if running:
        return status
    try:
        overdue = (now or utc_now()) >= parse_utc(str(record.get("deadline_at") or ""))
    except (TypeError, ValueError):
        overdue = False
    return "overdue-unsupervised" if overdue else "unsupervised"


def start_session(
    paths,
    *,
    env_name: str,
    blueprint_ref: str,
    state_ref: str,
    resource_generation: str,
    duration_seconds: int,
    expiry_action: str,
    now: datetime | None = None,
    pid: int | None = None,
) -> dict[str, Any]:
    current = now or utc_now()
    existing = load_session(paths, blueprint_ref)
    if existing is not None and effective_status(existing, now=current) in {
        "active",
        "executing",
    }:
        raise LifecycleBusy(
            "a supervised access session is already active for this blueprint"
        )
    session_id = (
        f"access-session-{current.strftime('%Y%m%dT%H%M%SZ')}-"
        f"{os.urandom(4).hex()}"
    )
    record: dict[str, Any] = {
        "schema_version": SESSION_SCHEMA_VERSION,
        "session_id": session_id,
        "env": env_name,
        "blueprint_ref": blueprint_ref,
        "state_ref": state_ref,
        "resource_generation": resource_generation,
        "status": "active",
        "started_at": format_utc(current),
        "deadline_at": format_utc(current + timedelta(seconds=duration_seconds)),
        "duration_seconds": duration_seconds,
        "expiry_action": expiry_action,
        "supervisor": {
            "host": socket.gethostname(),
            "pid": int(pid if pid is not None else os.getpid()),
        },
        "outcome": {},
    }
    if existing is not None:
        record["supersedes"] = str(existing.get("session_id") or "")
    save_session(paths, record, now=current)
    return record


def set_session_status(
    paths,
    record: dict[str, Any],
    status: str,
    *,
    reason: str = "",
    now: datetime | None = None,
) -> None:
    current = now or utc_now()
    record["status"] = status
    if reason:
        record["outcome"] = {"reason": reason}
    if status in SESSION_FINAL_STATES:
        record["completed_at"] = format_utc(current)
    save_session(paths, record, now=current)


def extend_session(
    paths,
    record: dict[str, Any],
    *,
    seconds: int,
    now: datetime | None = None,
) -> None:
    if str(record.get("status") or "") != "active":
        raise ValueError("only an active session can be extended")
    current = now or utc_now()
    deadline = parse_utc(str(record.get("deadline_at") or ""))
    if deadline <= current:
        raise ValueError("the session deadline has already passed")
    record["deadline_at"] = format_utc(deadline + timedelta(seconds=seconds))
    record["extension_count"] = int(record.get("extension_count") or 0) + 1
    save_session(paths, record, now=current)


def _pid_running(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    return True


class LifecycleLock(AbstractContextManager["LifecycleLock"]):
    def __init__(self, paths, operation: str) -> None:
        meta_dir = getattr(paths, "meta_dir", None)
        if meta_dir is None:
            state_dir = getattr(paths, "state_dir", None)
            if state_dir is not None:
                meta_dir = Path(state_dir).parent / "meta"
            else:
                meta_dir = Path(getattr(paths, "root")) / "meta"
        self.path = Path(meta_dir) / "blueprint_lifecycle.lock"
        self.owner_path = self.path / "owner.json"
        self.operation = operation
        self.token = os.urandom(8).hex()
        self.acquired = False

    def _owner(self) -> dict[str, Any]:
        try:
            data = json.loads(self.owner_path.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError):
            return {}
        return data if isinstance(data, dict) else {}

    def _clear_stale(self) -> bool:
        owner = self._owner()
        if not owner:
            try:
                age = utc_now().timestamp() - self.path.stat().st_mtime
            except OSError:
                return False
            if age < 30:
                return False
        elif str(owner.get("host") or "") != socket.gethostname():
            return False
        else:
            try:
                pid = int(owner.get("pid") or 0)
            except (TypeError, ValueError):
                pid = 0
            if _pid_running(pid):
                return False
        try:
            self.owner_path.unlink(missing_ok=True)
            self.path.rmdir()
        except OSError:
            return False
        return True

    def __enter__(self) -> "LifecycleLock":
        self.path.parent.mkdir(parents=True, exist_ok=True)
        for _attempt in range(2):
            try:
                self.path.mkdir(mode=0o700)
            except FileExistsError:
                if self._clear_stale():
                    continue
                owner = self._owner()
                detail = str(owner.get("operation") or "another lifecycle operation")
                raise LifecycleBusy(f"environment lifecycle is busy: {detail}")
            owner = {
                "token": self.token,
                "operation": self.operation,
                "pid": os.getpid(),
                "host": socket.gethostname(),
                "started_at": format_utc(utc_now()),
            }
            try:
                write_json_atomic(self.owner_path, owner)
            except Exception:
                try:
                    self.path.rmdir()
                except OSError:
                    pass
                raise
            self.acquired = True
            return self
        raise LifecycleBusy("environment lifecycle lock could not be acquired")

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        if not self.acquired:
            return None
        owner = self._owner()
        if str(owner.get("token") or "") == self.token:
            self.owner_path.unlink(missing_ok=True)
            try:
                self.path.rmdir()
            except OSError:
                pass
        self.acquired = False
        return None
