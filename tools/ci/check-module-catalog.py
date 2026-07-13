#!/usr/bin/env python3
"""Check that module contracts include their reviewable companion files."""

from __future__ import annotations

import sys
from pathlib import Path


def check_catalog(repo_root: Path) -> tuple[list[str], int]:
    modules_root = repo_root / "modules"
    failures: list[str] = []
    spec_paths = sorted(modules_root.rglob("spec.yml"))

    if not spec_paths:
        return ["modules: no spec.yml files found"], 0

    for spec_path in spec_paths:
        module_dir = spec_path.parent
        module_path = module_dir.relative_to(repo_root)

        if not (module_dir / "README.md").is_file():
            failures.append(f"{module_path}: missing README.md")

        examples_dir = module_dir / "examples"
        if not examples_dir.is_dir():
            failures.append(f"{module_path}: missing examples/")
        elif not any(path.is_file() for path in examples_dir.rglob("*")):
            failures.append(f"{module_path}: examples/ contains no files")

    return failures, len(spec_paths)


def main() -> int:
    repo_root = Path(__file__).resolve().parents[2]
    failures, module_count = check_catalog(repo_root)
    if failures:
        for failure in failures:
            print(f"ERR: {failure}", file=sys.stderr)
        return 1

    print(f"module catalog: ok ({module_count} modules)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
