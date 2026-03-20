#!/usr/bin/env bash
# purpose: Run HybridOps.Core YAML lint checks against maintained shipped YAML.
# adr: ADR-0622
# maintainer: HybridOps.Tech

set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=/dev/null
source "${SCRIPT_DIR}/lib/common.sh"

hyops_ci::require_cmd yamllint

mapfile -t targets < <(hyops_ci::all_yamllint_targets)
yamllint -c "${HYOPS_REPO_ROOT}/tools/ci/yamllint.yml" "${targets[@]}"
