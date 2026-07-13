#!/usr/bin/env bash
set -euo pipefail
# purpose: Shared low-level install helpers.
# Architecture Decision: ADR-N/A (bootstrap installer)
# maintainer: HybridOps.Tech

hyops_install_need_cmd() {
  command -v "$1" >/dev/null 2>&1 || {
    echo "ERR: missing command: $1" >&2
    exit 2
  }
}

hyops_install_is_windows_wsl() {
  local system_name="${HYOPS_TEST_SYSTEM_NAME:-}"
  if [[ -z "${system_name}" ]]; then
    system_name="$(uname -s 2>/dev/null || true)"
  fi
  [[ "${system_name}" == "Linux" ]] || return 1
  if [[ -n "${WSL_DISTRO_NAME:-}" || -n "${WSL_INTEROP:-}" ]]; then
    return 0
  fi

  local kernel_release="${HYOPS_TEST_KERNEL_RELEASE:-}"
  if [[ -z "${kernel_release}" ]]; then
    kernel_release="$(uname -r 2>/dev/null || true)"
  fi
  kernel_release="$(printf '%s' "${kernel_release}" | tr '[:upper:]' '[:lower:]')"
  [[ "${kernel_release}" == *microsoft* ]]
}

hyops_install_set_blueprint_payload_read_only() {
  local root="$1"
  local bp_root="${root}/blueprints"
  [[ -d "${bp_root}" ]] || return 0

  find "${bp_root}" -type d -exec chmod 0755 {} +
  find "${bp_root}" -type f \( -name '*.yml' -o -name '*.yaml' \) -exec chmod 0444 {} +
}

hyops_install_abs_path() {
  local raw_path="$1"
  python3 - "${raw_path}" <<'PY'
import os
import sys

print(os.path.abspath(os.path.expanduser(sys.argv[1])))
PY
}

hyops_install_remove_or_fail_dir() {
  local target_dir="$1"
  local label="$2"

  if [[ -d "${target_dir}" ]]; then
    if [[ "${FORCE}" == "true" ]]; then
      echo "[install] removing ${target_dir}"
      rm -rf "${target_dir}"
    else
      echo "ERR: ${label} already exists: ${target_dir} (use --force)" >&2
      exit 2
    fi
  fi
}
