#!/usr/bin/env python3
"""Validate the structural contract of HybridOps Core module specifications."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import yaml


EXPECTED_API_VERSION = "hybridops/v1"
EXPECTED_KIND = "ModuleSpec"


def _is_non_empty_string(value: Any) -> bool:
    """Return True when value is a non-empty string."""
    return isinstance(value, str) and bool(value.strip())


def _require_mapping(
    value: Any,
    path: str,
    failures: list[str],
) -> dict[str, Any] | None:
    """Validate that value is a mapping and return it when valid."""
    if not isinstance(value, dict):
        failures.append(f"{path}: expected a mapping")
        return None

    return value


def _require_list(
    value: Any,
    path: str,
    failures: list[str],
) -> list[Any] | None:
    """Validate that value is a list and return it when valid."""
    if not isinstance(value, list):
        failures.append(f"{path}: expected a list")
        return None

    return value


def validate_module_spec(
    spec_path: Path,
    repo_root: Path,
) -> list[str]:
    """Validate one ModuleSpec file and return human-readable failures.

    The validator intentionally checks the stable structural contract rather
    than attempting to validate provider-specific configuration. Provider
    behaviour remains the responsibility of the corresponding driver,
    validator, pack, or preflight implementation.
    """
    failures: list[str] = []

    try:
        data = yaml.safe_load(spec_path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        return [f"{spec_path}: unable to read YAML: {exc}"]

    if not isinstance(data, dict):
        return [f"{spec_path}: root document must be a mapping"]

    api_version = data.get("api_version")
    if api_version != EXPECTED_API_VERSION:
        failures.append(
            f"{spec_path}: api_version must be {EXPECTED_API_VERSION!r}"
        )

    kind = data.get("kind")
    if kind != EXPECTED_KIND:
        failures.append(f"{spec_path}: kind must be {EXPECTED_KIND!r}")

    module_ref = data.get("module_ref")
    if not _is_non_empty_string(module_ref):
        failures.append(f"{spec_path}: module_ref must be a non-empty string")
    else:
        expected_ref = str(
            spec_path.parent.relative_to(repo_root / "modules")
        ).replace("\\", "/")

        if module_ref != expected_ref:
            failures.append(
                f"{spec_path}: module_ref {module_ref!r} does not match "
                f"module path {expected_ref!r}"
            )

    metadata = _require_mapping(
        data.get("metadata"),
        f"{spec_path}: metadata",
        failures,
    )

    if metadata is not None:
        if not _is_non_empty_string(metadata.get("title")):
            failures.append(
                f"{spec_path}: metadata.title must be a non-empty string"
            )

        if not _is_non_empty_string(metadata.get("description")):
            failures.append(
                f"{spec_path}: metadata.description must be a non-empty string"
            )

    requirements = _require_mapping(
        data.get("requirements"),
        f"{spec_path}: requirements",
        failures,
    )

    if requirements is not None:
        _require_list(
            requirements.get("credentials"),
            f"{spec_path}: requirements.credentials",
            failures,
        )

    inputs = _require_mapping(
        data.get("inputs"),
        f"{spec_path}: inputs",
        failures,
    )

    if inputs is not None:
        _require_mapping(
            inputs.get("defaults"),
            f"{spec_path}: inputs.defaults",
            failures,
        )

    execution = _require_mapping(
        data.get("execution"),
        f"{spec_path}: execution",
        failures,
    )

    if execution is not None:
        if not _is_non_empty_string(execution.get("driver")):
            failures.append(
                f"{spec_path}: execution.driver must be a non-empty string"
            )

        if not _is_non_empty_string(execution.get("profile")):
            failures.append(
                f"{spec_path}: execution.profile must be a non-empty string"
            )

        pack_ref = _require_mapping(
            execution.get("pack_ref"),
            f"{spec_path}: execution.pack_ref",
            failures,
        )

        if pack_ref is not None and not _is_non_empty_string(pack_ref.get("id")):
            failures.append(
                f"{spec_path}: execution.pack_ref.id must be a non-empty string"
            )

    outputs = _require_mapping(
        data.get("outputs"),
        f"{spec_path}: outputs",
        failures,
    )

    if outputs is not None:
        _require_list(
            outputs.get("publish"),
            f"{spec_path}: outputs.publish",
            failures,
        )

        _require_list(
            outputs.get("probes"),
            f"{spec_path}: outputs.probes",
            failures,
        )

    _require_list(
        data.get("constraints"),
        f"{spec_path}: constraints",
        failures,
    )

    return failures


def check_module_contracts(repo_root: Path) -> tuple[list[str], int]:
    """Validate every module spec below the repository's modules directory."""
    modules_root = repo_root / "modules"

    if not modules_root.is_dir():
        return [f"{modules_root}: modules directory does not exist"], 0

    spec_paths = sorted(modules_root.rglob("spec.yml"))

    if not spec_paths:
        return [f"{modules_root}: no spec.yml files found"], 0

    failures: list[str] = []

    for spec_path in spec_paths:
        failures.extend(validate_module_spec(spec_path, repo_root))

    return failures, len(spec_paths)


def main() -> int:
    """Run module contract validation and return a process exit code."""
    repo_root = Path(__file__).resolve().parents[2]

    failures, module_count = check_module_contracts(repo_root)

    if failures:
        for failure in failures:
            print(f"ERR: {failure}", file=sys.stderr)

        print(
            f"module contracts: failed ({len(failures)} error(s), "
            f"{module_count} module(s) checked)",
            file=sys.stderr,
        )
        return 1

    print(f"module contracts: ok ({module_count} modules)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
