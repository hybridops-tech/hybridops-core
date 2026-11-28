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


def _write_exclusive(path: Path, payload: bytes, directory: int) -> tuple[int, int]:
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
            identity = os.fstat(stream.fileno())
        try:
            os.link(temporary, path.name, src_dir_fd=directory, dst_dir_fd=directory)
        except FileExistsError:
            raise FileExistsError(f"path already exists: {path}") from None
        _sync_directory(path.parent, directory)
        return identity.st_dev, identity.st_ino
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
    if path.is_dir():
        if os.access(path.parent, os.R_OK | os.W_OK):
            _sync_directory(path.parent)
        return
    _ensure_store_directory(path.parent)
    with _operation_directory(path.parent) as parent:
        try:
            os.mkdir(path.name, mode=0o700, dir_fd=parent)
        except FileExistsError:
            if not path.is_dir():
                raise
        _sync_directory(path.parent, parent)


@dataclass(frozen=True)
class OperationLease:
    record_path: Path


@dataclass(frozen=True)
class _FileOperationLease(OperationLease):
    directory_identity: tuple[int, int]
    claim_identity: tuple[int, int]
    claim_payload: bytes


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


def _matches_record(
    path: Path,
    directory: int,
    expected: bytes,
    *,
    identity: tuple[int, int] | None = None,
    sync: bool = False,
) -> bool | None:
    """Return None only when the entry is absent at open."""
    flags = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK
    try:
        descriptor = os.open(path.name, flags, dir_fd=directory)
    except FileNotFoundError:
        return None
    try:
        info = os.fstat(descriptor)
        if not stat.S_ISREG(info.st_mode):
            raise OSError("operation record is not a regular file")
        with os.fdopen(descriptor, "rb", closefd=False) as stream:
            matches = (
                (identity is None or (info.st_dev, info.st_ino) == identity)
                and info.st_size == len(expected)
                and stream.read(len(expected) + 1) == expected
            )
        if sync and matches:
            os.fsync(descriptor)
            _sync_directory(path.parent, directory)
        current = os.stat(path.name, dir_fd=directory, follow_symlinks=False)
        if not os.path.samestat(info, current):
            raise OSError("operation record changed during verification")
        return matches
    finally:
        os.close(descriptor)


def _verify_claim(lease: _FileOperationLease, directory: int) -> None:
    if not _matches_record(
        lease.record_path.with_name("claim.json"),
        directory,
        lease.claim_payload,
        identity=lease.claim_identity,
    ):
        raise OSError("operation claim no longer matches acquired lease")


@contextmanager
def _claimed_directory(lease: _FileOperationLease) -> Iterator[int]:
    with _operation_directory(
        lease.record_path.parent, lease.directory_identity
    ) as directory:
        _verify_claim(lease, directory)
        yield directory
        _verify_claim(lease, directory)


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
        bound_claim = _payload(
            {
                **claim,
                "terminal_record": str(record_path),
                "acquisition_id": uuid4().hex,
            }
        )
        with _operation_directory(operation_root) as directory:
            claim_identity = _write_exclusive(operation_path, bound_claim, directory)
            identity = os.fstat(directory)
            lease = _FileOperationLease(
                record_path,
                (identity.st_dev, identity.st_ino),
                claim_identity,
                bound_claim,
            )
            _verify_claim(lease, directory)
            return lease

    def terminal_path(self, operation_id: str) -> Path:
        operation_key = hashlib.sha256(operation_id.encode("utf-8")).hexdigest()
        return self._root / operation_key / "terminal.json"

    def publish(self, lease: OperationLease, record: dict[str, Any]) -> None:
        if not isinstance(lease, _FileOperationLease):
            raise TypeError("operation lease does not identify an acquired directory")
        try:
            with _claimed_directory(lease) as directory:
                _write_exclusive(lease.record_path, _payload(record), directory)
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
        try:
            with _claimed_directory(lease) as directory:
                matches = _matches_record(
                    lease.record_path, directory, expected, sync=True
                )
                if matches is None:
                    return PublicationState.ABSENT
                return (
                    PublicationState.COMMITTED if matches else PublicationState.CONFLICT
                )
        except OSError:
            return PublicationState.UNKNOWN
