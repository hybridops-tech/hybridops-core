#!/usr/bin/env bash
# purpose: Run HybridOps.Core Python source integrity checks.
# adr: ADR-0622
# maintainer: HybridOps.Tech

set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=/dev/null
source "${SCRIPT_DIR}/lib/common.sh"

hyops_ci::require_cmd python3

python3 -m compileall "${HYOPS_REPO_ROOT}/hyops"

python3 - "${HYOPS_REPO_ROOT}" <<'PY'
import importlib
import pkgutil
import sys
from pathlib import Path

repo_root = Path(sys.argv[1]).resolve()
sys.path.insert(0, str(repo_root))

import hyops  # noqa: E402

failures = []
for module_info in pkgutil.walk_packages(hyops.__path__, prefix="hyops."):
    try:
        importlib.import_module(module_info.name)
    except Exception as exc:  # pragma: no cover - CI only
        failures.append((module_info.name, exc))

if failures:
    for name, exc in failures:
        print(f"ERR: import failed for {name}: {exc}", file=sys.stderr)
    raise SystemExit(1)
PY

python3 - "${HYOPS_REPO_ROOT}" <<'PY'
import ast
import sys
from pathlib import Path

repo_root = Path(sys.argv[1]).resolve()
validators_root = repo_root / "hyops" / "validators"

shared_helper_names = {
    "check_no_placeholder",
    "require_bool",
    "require_int_ge",
    "require_non_empty_str",
    "opt_bool",
    "opt_int",
    "opt_mapping",
    "opt_str",
    "opt_str_list",
}
local_helper_names = {
    "_opt_bool",
    "_opt_int",
    "_opt_mapping",
    "_opt_str_list",
    "_req_bool",
}

failures: list[str] = []

for path in sorted(validators_root.rglob("*.py")):
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    imported: set[str] = set()
    defined: set[str] = set()
    used: set[str] = set()

    class Visitor(ast.NodeVisitor):
        def visit_ImportFrom(self, node):
            if node.module == "hyops.validators.common":
                for alias in node.names:
                    imported.add(alias.asname or alias.name)
            self.generic_visit(node)

        def visit_FunctionDef(self, node):
            defined.add(node.name)
            self.generic_visit(node)

        def visit_Name(self, node):
            if isinstance(node.ctx, ast.Load):
                used.add(node.id)

    Visitor().visit(tree)

    missing_shared = sorted((used & shared_helper_names) - imported - defined)
    missing_local = sorted((used & local_helper_names) - defined)
    if missing_shared or missing_local:
        details = ", ".join(missing_shared + missing_local)
        failures.append(f"{path.relative_to(repo_root)}: missing helper binding(s): {details}")

if failures:
    for entry in failures:
        print(f"ERR: {entry}", file=sys.stderr)
    raise SystemExit(1)
PY
