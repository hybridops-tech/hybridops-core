#!/usr/bin/env python3
"""Check that module spec.yml files satisfy the ModuleSpec contract shape.

purpose: Validate the top-level keys and types every module's spec.yml
         must provide so `hyops` can resolve, merge, and execute it. This
         complements check-module-catalog.py, which checks for a module's
         companion files (README.md, examples/) but does not inspect the
         contents of spec.yml itself.
maintainer: HybridOps.Tech
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import yaml

# Top-level keys every spec.yml must define. See any module under modules/
# for reference (e.g. modules/core/azure/resource-group/spec.yml).
REQUIRED_TOP_LEVEL_KEYS: tuple[str, ...] = (
    "api_version",
    "kind",
    "module_ref",
    "requirements",
    "inputs",
    "execution",
    "outputs",
)

EXPECTED_API_VERSION = "hybridops/v1"
EXPECTED_KIND = "ModuleSpec"


def _load_spec(spec_path: Path) -> dict[str, Any] | None:
    """Parse a spec.yml file and return its contents as a dict.

    Returns None (instead of raising) when the file cannot be read, is not
    valid YAML, or does not parse to a mapping. This lets the caller report
    one clear failure line rather than crashing the whole check on a single
    malformed file.
    """
    try:
        raw = spec_path.read_text(encoding="utf-8")
    except OSError:
        return None

    try:
        data = yaml.safe_load(raw)
    except yaml.YAMLError:
        return None

    if not isinstance(data, dict):
        return None

    return data


def validate_spec_schema(spec_path: Path, repo_root: Path) -> list[str]:
    """Validate a single spec.yml against the ModuleSpec contract shape.

    Args:
        spec_path: Absolute path to the spec.yml file being checked.
        repo_root: Repository root, used to render human-readable relative
            paths in failure messages and to derive the expected
            module_ref from the module's own directory location.

    Returns:
        A list of human-readable failure strings. An empty list means the
        spec passed every check performed by this function.
    """
    module_path = spec_path.parent.relative_to(repo_root)
    failures: list[str] = []

    data = _load_spec(spec_path)
    if data is None:
        return [f"{module_path}: spec.yml is missing, unreadable, or not a YAML mapping"]

    for key in REQUIRED_TOP_LEVEL_KEYS:
        if key not in data:
            failures.append(f"{module_path}: missing required key '{key}'")

    api_version = data.get("api_version")
    if api_version is not None and api_version != EXPECTED_API_VERSION:
        failures.append(
            f"{module_path}: api_version '{api_version}' does not match "
            f"expected '{EXPECTED_API_VERSION}'"
        )

    kind = data.get("kind")
    if kind is not None and kind != EXPECTED_KIND:
        failures.append(f"{module_path}: kind '{kind}' does not match expected '{EXPECTED_KIND}'")

    module_ref = data.get("module_ref")
    if module_ref is not None:
        if not isinstance(module_ref, str) or not module_ref.strip():
            failures.append(f"{module_path}: module_ref must be a non-empty string")
        elif module_ref.strip() != str(module_path):
            failures.append(
                f"{module_path}: module_ref '{module_ref}' does not match "
                f"its directory path '{module_path}'"
            )

    execution = data.get("execution")
    if execution is not None:
        if not isinstance(execution, dict):
            failures.append(f"{module_path}: 'execution' must be a mapping")
        else:
            driver = execution.get("driver")
            if not isinstance(driver, str) or not driver.strip():
                failures.append(f"{module_path}: execution.driver must be a non-empty string")

            profile = execution.get("profile")
            if not isinstance(profile, str) or not profile.strip():
                failures.append(f"{module_path}: execution.profile must be a non-empty string")

    requirements = data.get("requirements")
    if requirements is not None:
        if not isinstance(requirements, dict):
            failures.append(f"{module_path}: 'requirements' must be a mapping")
        else:
            credentials = requirements.get("credentials", [])
            if not isinstance(credentials, list):
                failures.append(f"{module_path}: requirements.credentials must be a list")

    outputs = data.get("outputs")
    if outputs is not None:
        if not isinstance(outputs, dict):
            failures.append(f"{module_path}: 'outputs' must be a mapping")
        else:
            publish = outputs.get("publish", [])
            if not isinstance(publish, list):
                failures.append(f"{module_path}: outputs.publish must be a list")

    return failures


def check_spec_schema(repo_root: Path) -> tuple[list[str], int]:
    """Validate every module's spec.yml under modules/ against the contract shape.

    Args:
        repo_root: Repository root containing the modules/ directory.

    Returns:
        A tuple of (all failure strings across every module, number of
        spec.yml files that were checked).
    """
    modules_root = repo_root / "modules"
    spec_paths = sorted(modules_root.rglob("spec.yml"))

    if not spec_paths:
        return ["modules: no spec.yml files found"], 0

    failures: list[str] = []
    for spec_path in spec_paths:
        failures.extend(validate_spec_schema(spec_path, repo_root))

    return failures, len(spec_paths)


def main() -> int:
    repo_root = Path(__file__).resolve().parents[2]
    failures, module_count = check_spec_schema(repo_root)

    if failures:
        for failure in failures:
            print(f"ERR: {failure}", file=sys.stderr)
        return 1

    print(f"module spec schema: ok ({module_count} modules)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
