#!/usr/bin/env bash
set -euo pipefail
# purpose: setup-all orchestration helpers for installer.
# Architecture Decision: ADR-N/A (bootstrap installer)
# maintainer: HybridOps.Tech

hyops_install_run_setup_all() {
  [[ "${SETUP_ALL}" == "true" ]] || return 0

  local setup_all_script="${APP_DIR}/tools/setup/setup-all.sh"
  if [[ ! -f "${setup_all_script}" ]]; then
    echo "ERR: setup-all not found: ${setup_all_script}" >&2
    exit 2
  fi

  echo "[install] running setup-all"
  if [[ "${EUID:-$(id -u)}" -eq 0 ]]; then
    bash "${setup_all_script}"
    return 0
  fi

  command -v sudo >/dev/null 2>&1 || {
    echo "ERR: sudo required for --setup-all" >&2
    exit 2
  }

  sudo -E bash "${setup_all_script}"
}
