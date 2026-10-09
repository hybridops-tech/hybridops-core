"""Validate protected input and retained evidence paths for pinned workloads."""

from __future__ import annotations

from typing import Any

from hyops.validators.common import normalize_lifecycle_command, require_mapping
from hyops.validators.registry import ModuleValidationError


def _relative_path(value: Any, field: str, *, allow_root: bool) -> tuple[str, ...]:
    if not isinstance(value, str) or not value:
        raise ModuleValidationError(f"{field} must be a non-empty string")
    if value != value.strip():
        raise ModuleValidationError(f"{field} must not contain surrounding whitespace")
    if value.startswith("/"):
        raise ModuleValidationError(f"{field} must be relative to the workload checkout")
    if allow_root and value == ".":
        return ()

    parts = tuple(value.split("/"))
    if any(part in {"", ".", ".."} for part in parts):
        raise ModuleValidationError(f"{field} must be a canonical relative path")
    return parts


def _paths_overlap(left: tuple[str, ...], right: tuple[str, ...]) -> bool:
    common_length = min(len(left), len(right))
    return left[:common_length] == right[:common_length]


def validate(inputs: dict[str, Any]) -> None:
    data = require_mapping(inputs, "inputs")

    runtime_files = data.get("pinned_workload_runtime_files")
    if not isinstance(runtime_files, list):
        raise ModuleValidationError("inputs.pinned_workload_runtime_files must be a list")

    evidence_paths = data.get("pinned_workload_evidence_paths")
    if not isinstance(evidence_paths, list):
        raise ModuleValidationError("inputs.pinned_workload_evidence_paths must be a list")

    if normalize_lifecycle_command(data) == "destroy":
        return

    runtime_paths: list[tuple[str, tuple[str, ...]]] = []
    for index, declaration in enumerate(runtime_files, start=1):
        field = f"inputs.pinned_workload_runtime_files[{index}]"
        if not isinstance(declaration, dict):
            raise ModuleValidationError(f"{field} must be a mapping")
        destination = declaration.get("dest")
        parts = _relative_path(destination, f"{field}.dest", allow_root=False)
        runtime_paths.append((str(destination), parts))

    retained_paths: list[tuple[str, tuple[str, ...]]] = []
    for index, path in enumerate(evidence_paths, start=1):
        parts = _relative_path(
            path,
            f"inputs.pinned_workload_evidence_paths[{index}]",
            allow_root=True,
        )
        retained_paths.append((str(path), parts))

    for destination, runtime_parts in runtime_paths:
        for evidence_path, evidence_parts in retained_paths:
            if _paths_overlap(runtime_parts, evidence_parts):
                raise ModuleValidationError(
                    f"Protected runtime destination '{destination}' overlaps retained "
                    f"evidence path '{evidence_path}'."
                )
