#!/usr/bin/env bash
# purpose: Load and enforce pinned tool versions from tools/setup/requirements/toolchain.lock.
# architecture decision: ADR-N/A
# maintainer: HybridOps.Tech

set -euo pipefail

toolchain__die() { echo "ERR: $*" >&2; exit 2; }

toolchain__script_dir() { cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd; }

toolchain__release_root() {
  local d
  d="$(toolchain__script_dir)"
  # tools/setup/lib -> <release_root>
  cd -- "${d}/../../.." && pwd
}

toolchain__lock_path() {
  if [[ -n "${HYOPS_TOOLCHAIN_LOCK:-}" ]]; then
    echo "${HYOPS_TOOLCHAIN_LOCK}"
    return 0
  fi
  echo "$(toolchain__release_root)/tools/setup/requirements/toolchain.lock"
}

toolchain__load() {
  local p
  p="$(toolchain__lock_path)"
  [[ -f "${p}" ]] || toolchain__die "missing toolchain lock file: ${p}"

  # shellcheck disable=SC1090
  set -a
  source "${p}"
  set +a
}

toolchain_get() {
  local key="$1"
  toolchain__load
  # shellcheck disable=SC2154
  local val="${!key:-}"
  echo "${val}"
}

toolchain_require() {
  local key="$1"
  local val
  val="$(toolchain_get "${key}")"
  [[ -n "${val}" ]] || toolchain__die "required key not set in toolchain.lock: ${key}"
  echo "${val}"
}
