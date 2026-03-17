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
