"""Verify retained recovery bytes immediately before destructive dispatch."""

from __future__ import annotations

import hashlib
from contextlib import AbstractContextManager
from time import monotonic
from typing import BinaryIO, Protocol

from .errors import ContractFailure
from .models import EvidenceBinding, WorkloadIdentity

_CHUNK_BYTES = 1024 * 1024


class RetainedEvidenceReader(Protocol):
    def open_evidence(
        self,
        operation_id: str,
        workload: WorkloadIdentity,
        producer_stage: str,
        name: str,
        role: str,
        *,
        deadline: float,
    ) -> AbstractContextManager[BinaryIO]:
        """Open retained bytes independently of stage outputs; bound I/O by the monotonic deadline."""
        ...


def _check_deadline(deadline: float) -> None:
    if monotonic() >= deadline:
        raise TimeoutError


def _digest(stream: BinaryIO, deadline: float) -> str:
    value = hashlib.sha256()
    while True:
        _check_deadline(deadline)
        chunk = stream.read(_CHUNK_BYTES)
        if type(chunk) is not bytes or len(chunk) > _CHUNK_BYTES:
            raise ValueError("invalid binary read")
        if not chunk:
            return "sha256:" + value.hexdigest()
        value.update(chunk)


def verify_retained(
    reader: RetainedEvidenceReader | None,
    operation_id: str,
    workload: WorkloadIdentity,
    required: tuple[tuple[EvidenceBinding, str], ...],
    timeout: float,
) -> None:
    if reader is None or not required:
        raise ContractFailure(
            "retained_evidence_unavailable", "no retained evidence to verify"
        )
    deadline = monotonic() + timeout
    for binding, expected in required:
        label = f"{binding.stage}/{binding.name}:{binding.role}"
        actual = None
        try:
            _check_deadline(deadline)
            with reader.open_evidence(
                operation_id,
                workload,
                binding.stage,
                binding.name,
                binding.role,
                deadline=deadline,
            ) as stream:
                actual = _digest(stream, deadline)
            _check_deadline(deadline)
            if actual is None:  # The context manager suppressed a failed read.
                raise ValueError("incomplete evidence read")
        except Exception:  # The storage backend can include credentials in its errors.
            raise ContractFailure(
                "retained_evidence_unavailable",
                f"could not verify retained evidence '{label}'",
            ) from None
        if actual != expected:
            raise ContractFailure(
                "retained_evidence_mismatch",
                f"retained evidence '{label}' does not match its producer",
            )
