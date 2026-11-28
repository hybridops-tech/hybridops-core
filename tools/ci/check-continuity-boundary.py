#!/usr/bin/env python3
"""Reject platform and execution-engine dependencies in the continuity kernel."""

from __future__ import annotations

import ast
import json
import subprocess
import sys
from collections.abc import Iterator
from pathlib import Path

ALLOWED_HYOPS_IMPORTS = frozenset(
    {
        "hyops.authority.models",
    }
)
ALLOWED_EXTERNAL_IMPORTS = frozenset()
DISALLOWED_DYNAMIC_IMPORT_MODULES = frozenset({"importlib"})
ALLOWED_RUNTIME_MODULES = frozenset(
    {
        "hyops",
        "hyops.authority",
        "hyops.authority.models",
    }
)


def imported_modules(
    path: Path,
    repo_root: Path,
    *,
    eager_only: bool = False,
) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    modules: set[str] = set()
    package = path.relative_to(repo_root).parent.parts
    nodes = _eager_nodes(tree) if eager_only else ast.walk(tree)
    for node in nodes:
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                retained = len(package) - (node.level - 1)
                if retained < 0:
                    modules.add("<invalid-relative-import>")
                    continue
                prefix = package[:retained]
                suffix = tuple(node.module.split(".")) if node.module else ()
                modules.add(".".join((*prefix, *suffix)))
            elif node.module:
                modules.add(node.module)
    return modules


def _eager_nodes(tree: ast.AST) -> Iterator[ast.AST]:
    pending = list(ast.iter_child_nodes(tree))
    while pending:
        node = pending.pop()
        yield node
        if isinstance(
            node,
            (ast.AsyncFunctionDef, ast.FunctionDef, ast.Lambda),
        ):
            continue
        pending.extend(ast.iter_child_nodes(node))


def dynamic_import_calls(
    path: Path,
    *,
    eager_only: bool = False,
) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    nodes = _eager_nodes(tree) if eager_only else ast.walk(tree)
    calls: set[str] = set()
    for node in nodes:
        if not isinstance(node, ast.Call):
            continue
        function = node.func
        if isinstance(function, ast.Name) and function.id in {
            "__import__",
            "import_module",
        }:
            calls.add(function.id)
        elif isinstance(function, ast.Attribute) and function.attr in {
            "__import__",
            "import_module",
        }:
            calls.add(function.attr)
    return calls


def _package_initializers(path: Path, repo_root: Path) -> set[Path]:
    relative = path.relative_to(repo_root)
    initializers: set[Path] = set()
    parent = relative.parent
    while parent.parts:
        candidate = repo_root / parent / "__init__.py"
        if candidate.is_file():
            initializers.add(candidate)
        parent = parent.parent
    return initializers


def _runtime_modules(repo_root: Path) -> set[str]:
    script = """
import json
import sys
sys.path.insert(0, sys.argv[1])
import hyops.continuity
print(json.dumps(sorted(name for name in sys.modules if name.startswith('hyops'))))
"""
    result = subprocess.run(
        [sys.executable, "-I", "-c", script, str(repo_root)],
        check=True,
        capture_output=True,
        text=True,
    )
    return set(json.loads(result.stdout))


def main() -> int:
    repo_root = Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else Path.cwd()
    kernel = repo_root / "hyops" / "continuity"
    failures: list[str] = []
    if not kernel.is_dir():
        print("ERR: continuity kernel is missing", file=sys.stderr)
        return 1
    paths: dict[Path, bool] = {path: False for path in kernel.rglob("*.py")}
    for module in ALLOWED_HYOPS_IMPORTS:
        path = repo_root.joinpath(*module.split(".")).with_suffix(".py")
        paths[path] = False
        for initializer in _package_initializers(path, repo_root):
            paths.setdefault(initializer, True)
    for path, eager_only in sorted(paths.items()):
        if kernel in path.parents and "tests" in path.relative_to(kernel).parts:
            continue
        for module in sorted(imported_modules(path, repo_root, eager_only=eager_only)):
            if module == "<invalid-relative-import>":
                failures.append(
                    f"{path.relative_to(repo_root)} contains an invalid relative import"
                )
                continue
            if not module.startswith("hyops."):
                root_module = module.split(".", 1)[0]
                if root_module in DISALLOWED_DYNAMIC_IMPORT_MODULES:
                    failures.append(
                        f"{path.relative_to(repo_root)} imports disallowed dynamic "
                        f"loader {module}"
                    )
                    continue
                if (
                    root_module not in sys.stdlib_module_names
                    and root_module not in ALLOWED_EXTERNAL_IMPORTS
                ):
                    failures.append(
                        f"{path.relative_to(repo_root)} imports disallowed external "
                        f"module {module}"
                    )
                continue
            if module.startswith("hyops.continuity"):
                continue
            if module not in ALLOWED_HYOPS_IMPORTS:
                failures.append(
                    f"{path.relative_to(repo_root)} imports disallowed module {module}"
                )
        for function in sorted(dynamic_import_calls(path, eager_only=eager_only)):
            failures.append(
                f"{path.relative_to(repo_root)} calls disallowed dynamic loader "
                f"{function}"
            )
    try:
        runtime_modules = _runtime_modules(repo_root)
    except (OSError, subprocess.CalledProcessError, ValueError) as exc:
        failures.append(f"continuity runtime import check failed: {exc}")
    else:
        for module in sorted(runtime_modules):
            if module.startswith("hyops.continuity"):
                continue
            if module not in ALLOWED_RUNTIME_MODULES:
                failures.append(
                    f"continuity runtime imports disallowed module {module}"
                )
    if failures:
        for failure in failures:
            print(f"ERR: {failure}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
