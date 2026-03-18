#!/usr/bin/env bash
set -euo pipefail
# purpose: High-level installer orchestration for HybridOps.Core.
# Architecture Decision: ADR-N/A (bootstrap installer)
# maintainer: HybridOps.Tech

_hyops_install_lib_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"

# shellcheck source=/dev/null
source "${_hyops_install_lib_dir}/common.sh"
# shellcheck source=/dev/null
source "${_hyops_install_lib_dir}/python_env.sh"
# shellcheck source=/dev/null
source "${_hyops_install_lib_dir}/payload.sh"
# shellcheck source=/dev/null
source "${_hyops_install_lib_dir}/wrapper.sh"
# shellcheck source=/dev/null
source "${_hyops_install_lib_dir}/setup.sh"

hyops_install_run() {
  hyops_install_need_cmd python3
  hyops_install_need_cmd cp
  hyops_install_need_cmd mkdir
  hyops_install_need_cmd find

  PREFIX="$(hyops_install_abs_path "${PREFIX}")"
  BIN_DIR="$(hyops_install_abs_path "${BIN_DIR}")"

  APP_DIR="${PREFIX}/app"
  VENV_DIR="${PREFIX}/venv"

  RUNTIME_ROOT="${HOME}/.hybridops"
  TOOLS_DIR="${RUNTIME_ROOT}/tools"
  VAULT_PASS_SRC="${SRC_ROOT}/tools/secrets/vault/vault-pass.sh"
  VAULT_PASS_DST="${TOOLS_DIR}/vault-pass.sh"

  WHEELHOUSE_OVERRIDE="${HYOPS_WHEELHOUSE:-}"
  USE_SYSTEM_DEPS="${HYOPS_INSTALL_USE_SYSTEM_DEPS:-false}"
  INSTALL_NO_DEPS="${HYOPS_INSTALL_NO_DEPS:-false}"

  mkdir -p "${PREFIX}" "${RUNTIME_ROOT}" "${TOOLS_DIR}"

  echo "[install] prefix=${PREFIX}"
  echo "[install] bin_dir=${BIN_DIR}"

  if [[ "${SETUP_ALL}" == "auto" ]]; then
    if [[ "${SYSTEM_LINK}" == "true" ]]; then
      SETUP_ALL="true"
    else
      SETUP_ALL="false"
    fi
  fi
  echo "[install] setup_all=${SETUP_ALL}"

  if [[ "${SYSTEM_LINK}" == "true" ]]; then
    hyops_install_need_cmd sudo
    echo "[install] sudo required for /usr/local/bin/hyops"
    sudo -v || {
      echo "ERR: sudo cancelled; global hyops not installed" >&2
      exit 3
    }
  fi

  hyops_install_remove_or_fail_dir "${APP_DIR}" "app dir"
  hyops_install_copy_payload

  hyops_install_remove_or_fail_dir "${VENV_DIR}" "venv dir"
  hyops_install_create_venv_and_payload

  hyops_install_normalize_payload_permissions
  hyops_install_install_vault_helper

  hyops_install_install_user_wrapper
  hyops_install_install_system_link
  hyops_install_run_setup_all

  echo "[install] OK"
  echo "Try:"
  echo "  hyops --help"
  echo "  hyops preflight"
  if [[ -n "${WRAPPER:-}" ]]; then
    echo "  ${WRAPPER} --help"
  fi
}
