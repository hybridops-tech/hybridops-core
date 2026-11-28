"""Exclusive operation ownership and terminal evidence persistence."""

from __future__ import annotations

import hashlib
import json
import os
import stat
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Protocol
from uuid import uuid4


def _payload(value: Any) -> bytes:
    return (json.dumps(value, allow_nan=False, indent=2, sort_keys=True) + "\n").encode(
        "utf-8"
    )


def _write_exclusive(path: Path, value: Any, directory: int) -> None:
    payload = _payload(value)
    temporary = f".{path.name}.{uuid4().hex}"
    descriptor = os.open(
        temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600, dir_fd=directory
    )
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fchmod(stream.fileno(), 0o600)
            os.fsync(stream.fileno())
        try:
            os.link(temporary, path.name, src_dir_fd=directory, dst_dir_fd=directory)
        except FileExistsError:
            raise FileExistsError(f"path already exists: {path}") from None
        _sync_directory(path.parent, directory)
    finally:
        try:
            os.unlink(temporary, dir_fd=directory)
        except FileNotFoundError:
            pass


def _sync_directory(path: Path, directory: int | None = None) -> None:
    if directory is not None:
        os.fsync(directory)
        return
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _ensure_store_directory(path: Path) -> None:
    if not path.is_dir():
        _ensure_store_directory(path.parent)
        path.mkdir(mode=0o700, exist_ok=True)
    elif not os.access(path.parent, os.W_OK):
        # A pre-provisioned directory below a read-only parent is the storage anchor.
        return
    _sync_directory(path.parent)


@dataclass(frozen=True)
class OperationLease:
    record_path: Path


@dataclass(frozen=True)
class _FileOperationLease(OperationLease):
    directory_identity: tuple[int, int]


@contextmanager
def _operation_directory(
    path: Path, expected: tuple[int, int] | None = None
) -> Iterator[int]:
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_DIRECTORY", 0)
    directory = os.open(path, flags)
    try:
        identity = os.fstat(directory)
        if expected is not None and (identity.st_dev, identity.st_ino) != expected:
            raise OSError("operation directory no longer matches acquired lease")
        yield directory
        if not os.path.samestat(identity, path.stat(follow_symlinks=False)):
            raise OSError("operation directory changed during publication")
    finally:
        os.close(directory)


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
        self._root = root.resolve()

    def acquire(
        self,
        operation_id: str,
        claim: dict[str, Any],
    ) -> OperationLease:
        if claim.get("operation_id") != operation_id:
            raise ValueError("operation claim identity does not match")
        operation_key = hashlib.sha256(operation_id.encode("utf-8")).hexdigest()
        _ensure_store_directory(self._root)
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
        bound_claim["terminal_record"] = str(record_path)
        with _operation_directory(operation_root) as directory:
            _write_exclusive(operation_path, bound_claim, directory)
            identity = os.fstat(directory)
            return _FileOperationLease(record_path, (identity.st_dev, identity.st_ino))

    def terminal_path(self, operation_id: str) -> Path:
        operation_key = hashlib.sha256(operation_id.encode("utf-8")).hexdigest()
        return self._root / operation_key / "terminal.json"

    def publish(self, lease: OperationLease, record: dict[str, Any]) -> None:
        if not isinstance(lease, _FileOperationLease):
            raise TypeError("operation lease does not identify an acquired directory")
        try:
            with _operation_directory(
                lease.record_path.parent, lease.directory_identity
            ) as directory:
                _write_exclusive(lease.record_path, record, directory)
        except FileExistsError:
            if self.probe(lease, record) is PublicationState.COMMITTED:
                return
            raise

    @staticmethod
    def probe(
        lease: OperationLease,
        record: dict[str, Any],
    ) -> PublicationState:
        if not isinstance(lease, _FileOperationLease):
            return PublicationState.UNKNOWN
        expected = _payload(record)
        flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
        try:
            with _operation_directory(
                lease.record_path.parent, lease.directory_identity
            ) as directory:
                try:
                    descriptor = os.open(lease.record_path.name, flags, dir_fd=directory)
                except FileNotFoundError:
                    claim = os.stat("claim.json", dir_fd=directory, follow_symlinks=False)
                    if stat.S_ISREG(claim.st_mode):
                        return PublicationState.ABSENT
                    return PublicationState.UNKNOWN
                with os.fdopen(descriptor, "rb") as stream:
                    if stream.read() != expected:
                        return PublicationState.CONFLICT
                    file_identity = os.fstat(stream.fileno())
                    os.fsync(stream.fileno())
                _sync_directory(lease.record_path.parent, directory)
                path_identity = os.stat(
                    lease.record_path.name, dir_fd=directory, follow_symlinks=False
                )
                if os.path.samestat(file_identity, path_identity):
                    return PublicationState.COMMITTED
                return PublicationState.UNKNOWN
        except OSError:
            return PublicationState.UNKNOWN
