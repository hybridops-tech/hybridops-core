#!/usr/bin/env bash
# purpose: Run HybridOps.Core Python lint checks against shipped Python sources.
# adr: ADR-0622
# maintainer: HybridOps.Tech

set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=/dev/null
source "${SCRIPT_DIR}/lib/common.sh"

hyops_ci::require_cmd ruff

mapfile -t targets < <(hyops_ci::all_python_quality_targets)
ruff check --config "${HYOPS_REPO_ROOT}/tools/ci/ruff.toml" "${targets[@]}"
