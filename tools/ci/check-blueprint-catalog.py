#!/usr/bin/env python3
"""Check that shipped blueprint contracts load, match their directory path, and resolve step modules."""

from __future__ import annotations

import sys
from pathlib import Path

repo_root = Path(__file__).resolve().parents[2]
if str(repo_root) not in sys.path:
    sys.path.insert(0, str(repo_root))

from hyops.blueprint.schema import load_blueprint, validate_blueprint


def check_blueprint_catalog(repo_root: Path) -> tuple[list[str], int]:
    blueprints_root = repo_root / "blueprints"
    modules_root = repo_root / "modules"
    failures: list[str] = []

    blueprint_paths = sorted(blueprints_root.rglob("blueprint.yml")) + sorted(
        blueprints_root.rglob("blueprint.yaml")
    )

    if not blueprint_paths:
        return ["blueprints: no blueprint.yml files found"], 0

    for path in blueprint_paths:
        rel_path = path.relative_to(repo_root)

        try:
            raw_payload = load_blueprint(path)
            spec = validate_blueprint(raw_payload, path)
        except Exception as exc:
            failures.append(f"{rel_path}: {exc}")
            continue

        # Confirm blueprint_ref matches its path under blueprints/
        expected_ref = path.parent.relative_to(blueprints_root).as_posix()
        blueprint_ref = spec.get("blueprint_ref", "")
        if blueprint_ref != expected_ref:
            failures.append(
                f"{rel_path}: blueprint_ref mismatch: expected {expected_ref!r}, got {blueprint_ref!r}"
            )

        # Confirm every step module_ref resolves to modules/<module_ref>/spec.yml
        module_refs: list[tuple[str, str]] = []
        for idx, step in enumerate(spec.get("steps", []), start=1):
            if isinstance(step, dict) and "module_ref" in step:
                module_refs.append((f"steps[{idx}].module_ref", step["module_ref"]))

        if (
            spec.get("archive_before_destroy")
            and isinstance(spec["archive_before_destroy"], dict)
            and spec["archive_before_destroy"].get("module_ref")
        ):
            module_refs.append(
                (
                    "archive_before_destroy.module_ref",
                    spec["archive_before_destroy"]["module_ref"],
                )
            )

        for ref_name, mod_ref in module_refs:
            clean_ref = mod_ref.split("@")[0]
            spec_path = modules_root / clean_ref / "spec.yml"
            if not spec_path.is_file():
                failures.append(
                    f"{rel_path}: {ref_name} {mod_ref!r} does not resolve to spec.yml at {spec_path.relative_to(repo_root)}"
                )

    return failures, len(blueprint_paths)


def main() -> int:
    repo_root = Path(__file__).resolve().parents[2]
    failures, blueprint_count = check_blueprint_catalog(repo_root)
    if failures:
        for failure in failures:
            print(f"ERR: {failure}", file=sys.stderr)
        return 1

    print(f"blueprint catalog: ok ({blueprint_count} blueprints)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
