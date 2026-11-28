"""Exclusive operation ownership and terminal evidence persistence."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Protocol


def _payload(value: Any) -> bytes:
    return (json.dumps(value, allow_nan=False, indent=2, sort_keys=True) + "\n").encode(
        "utf-8"
    )


def _write_exclusive(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = _payload(value)
    descriptor, temporary = tempfile.mkstemp(
        prefix=f".{path.name}.",
        dir=str(path.parent),
    )
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temporary, 0o600)
        try:
            os.link(temporary, path)
        except FileExistsError:
            raise FileExistsError(f"path already exists: {path}") from None
        _sync_directory(path.parent)
    finally:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass


def _sync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


@dataclass(frozen=True)
class OperationLease:
    record_path: Path


class PublicationState(str, Enum):
    ABSENT = "absent"
    COMMITTED = "committed"
    CONFLICT = "conflict"
    UNKNOWN = "unknown"


class OperationStore(Protocol):
    def acquire(
        self,
        operation_id: str,
        claim: dict[str, Any],
    ) -> OperationLease: ...

    def publish(self, lease: OperationLease, record: dict[str, Any]) -> None: ...

    def probe(
        self,
        lease: OperationLease,
        record: dict[str, Any],
    ) -> PublicationState: ...


class FileOperationStore:
    """Filesystem operation store with durable ownership and immutable records."""

    def __init__(self, root: Path) -> None:
        self._root = root

    def acquire(
        self,
        operation_id: str,
        claim: dict[str, Any],
    ) -> OperationLease:
        if claim.get("operation_id") != operation_id:
            raise ValueError("operation claim identity does not match")
        operation_key = hashlib.sha256(operation_id.encode("utf-8")).hexdigest()
        self._root.mkdir(parents=True, exist_ok=True, mode=0o700)
        operation_root = self._root / operation_key
        try:
            operation_root.mkdir(mode=0o700)
        except FileExistsError:
            raise FileExistsError(
                f"continuity operation already exists: {operation_id}"
            ) from None
        _sync_directory(self._root)
        operation_path = operation_root / "claim.json"
        record_path = operation_root / "terminal.json"
        bound_claim = dict(claim)
        bound_claim["terminal_record"] = str(record_path.resolve(strict=False))
        _write_exclusive(operation_path, bound_claim)
        return OperationLease(record_path=record_path)

    def terminal_path(self, operation_id: str) -> Path:
        operation_key = hashlib.sha256(operation_id.encode("utf-8")).hexdigest()
        return self._root / operation_key / "terminal.json"

    def publish(self, lease: OperationLease, record: dict[str, Any]) -> None:
        try:
            _write_exclusive(lease.record_path, record)
        except FileExistsError:
            if self.probe(lease, record) is PublicationState.COMMITTED:
                return
            raise

    @staticmethod
    def probe(
        lease: OperationLease,
        record: dict[str, Any],
    ) -> PublicationState:
        expected = _payload(record)
        try:
            descriptor = os.open(
                lease.record_path,
                os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0),
            )
        except FileNotFoundError:
            return PublicationState.ABSENT
        except OSError:
            return PublicationState.UNKNOWN
        try:
            with os.fdopen(descriptor, "rb") as stream:
                if stream.read() != expected:
                    return PublicationState.CONFLICT
                file_identity = os.fstat(stream.fileno())
                os.fsync(stream.fileno())
            _sync_directory(lease.record_path.parent)
            path_identity = lease.record_path.stat(follow_symlinks=False)
        except OSError:
            return PublicationState.UNKNOWN
        if (
            file_identity.st_dev,
            file_identity.st_ino,
        ) != (
            path_identity.st_dev,
            path_identity.st_ino,
        ):
            return PublicationState.UNKNOWN
        return PublicationState.COMMITTED
