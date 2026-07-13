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

hyops_install_run() (
  _hyops_install_run_transaction
)

_hyops_install_run_transaction() {
  hyops_install_need_cmd python3
  hyops_install_need_cmd cp
  hyops_install_need_cmd mkdir
  hyops_install_need_cmd find

  PREFIX="$(hyops_install_abs_path "${PREFIX}")"
  BIN_DIR="$(hyops_install_abs_path "${BIN_DIR}")"

  HYOPS_INSTALL_TX_FINAL_PREFIX="${PREFIX}"
  HYOPS_INSTALL_TX_STAGE_PREFIX="${PREFIX}.install.$$"
  HYOPS_INSTALL_TX_PREVIOUS_PREFIX="${PREFIX}.previous.$$"
  HYOPS_INSTALL_TX_HAD_PREVIOUS="false"
  HYOPS_INSTALL_TX_ACTIVATED="false"
  HYOPS_INSTALL_TX_COMPLETED="false"

  hyops_install_transaction_cleanup() {
    local exit_code=$?
    trap - EXIT HUP INT TERM
    set +e
    if [[ "${HYOPS_INSTALL_TX_COMPLETED}" != "true" && "${HYOPS_INSTALL_TX_ACTIVATED}" == "true" ]]; then
      echo "[install] installation failed; restoring previous installation" >&2
      rm -rf "${HYOPS_INSTALL_TX_FINAL_PREFIX}"
      if [[ "${HYOPS_INSTALL_TX_HAD_PREVIOUS}" == "true" && -d "${HYOPS_INSTALL_TX_PREVIOUS_PREFIX}" ]]; then
        mv "${HYOPS_INSTALL_TX_PREVIOUS_PREFIX}" "${HYOPS_INSTALL_TX_FINAL_PREFIX}"
      fi
    fi
    rm -rf "${HYOPS_INSTALL_TX_STAGE_PREFIX}" "${HYOPS_INSTALL_TX_PREVIOUS_PREFIX}"
    return "${exit_code}"
  }
  trap hyops_install_transaction_cleanup EXIT HUP INT TERM

  APP_DIR="${HYOPS_INSTALL_TX_STAGE_PREFIX}/app"
  VENV_DIR="${HYOPS_INSTALL_TX_STAGE_PREFIX}/venv"
  SYSTEM_LINK_PATH="${HYOPS_INSTALL_SYSTEM_LINK_PATH:-/usr/local/bin/hyops}"
  SYSTEM_LINK_DIR="$(dirname -- "${SYSTEM_LINK_PATH}")"

  RUNTIME_ROOT="${HOME}/.hybridops"
  TOOLS_DIR="${RUNTIME_ROOT}/tools"
  VAULT_PASS_SRC="${SRC_ROOT}/tools/secrets/vault/vault-pass.sh"
  VAULT_PASS_DST="${TOOLS_DIR}/vault-pass.sh"

  WHEELHOUSE_OVERRIDE="${HYOPS_WHEELHOUSE:-}"
  USE_SYSTEM_DEPS="${HYOPS_INSTALL_USE_SYSTEM_DEPS:-false}"
  INSTALL_NO_DEPS="${HYOPS_INSTALL_NO_DEPS:-false}"

  mkdir -p "$(dirname -- "${PREFIX}")" "${RUNTIME_ROOT}" "${TOOLS_DIR}"

  echo "[install] prefix=${PREFIX}"
  echo "[install] bin_dir=${BIN_DIR}"

  if [[ "${SETUP_ALL}" == "auto" ]]; then
    if [[ "$(uname -s 2>/dev/null || true)" == "Darwin" ]]; then
      # Homebrew refuses to run as root. Leave prerequisite installation as an
      # explicit setup step owned by the macOS user.
      SETUP_ALL="false"
      echo "[install] macOS detected; automatic setup-all is disabled"
    elif [[ "${SYSTEM_LINK}" == "true" ]]; then
      SETUP_ALL="true"
    else
      SETUP_ALL="false"
    fi
  fi
  echo "[install] setup_all=${SETUP_ALL}"

  if [[ "${SYSTEM_LINK}" == "true" ]]; then
    if [[ "${EUID:-$(id -u)}" -eq 0 ]]; then
      echo "[install] running as root; skipping sudo preflight for ${SYSTEM_LINK_PATH}"
    else
      hyops_install_need_cmd sudo
      echo "[install] sudo required for ${SYSTEM_LINK_PATH}"
      sudo -v || {
        echo "ERR: sudo cancelled; global hyops not installed" >&2
        exit 3
      }
    fi
  fi

  if [[ -e "${HYOPS_INSTALL_TX_FINAL_PREFIX}" && "${FORCE}" != "true" ]]; then
    echo "ERR: install prefix already exists: ${HYOPS_INSTALL_TX_FINAL_PREFIX} (use --force)" >&2
    exit 2
  fi
  rm -rf "${HYOPS_INSTALL_TX_STAGE_PREFIX}" "${HYOPS_INSTALL_TX_PREVIOUS_PREFIX}"

  hyops_install_copy_payload
  hyops_install_create_venv_and_payload

  echo "[install] verifying candidate"
  "${VENV_DIR}/bin/hyops" --help >/dev/null

  echo "[install] activating installation"
  hyops_install_relocate_venv "${HYOPS_INSTALL_TX_STAGE_PREFIX}" "${HYOPS_INSTALL_TX_FINAL_PREFIX}"
  if [[ -e "${HYOPS_INSTALL_TX_FINAL_PREFIX}" ]]; then
    mv "${HYOPS_INSTALL_TX_FINAL_PREFIX}" "${HYOPS_INSTALL_TX_PREVIOUS_PREFIX}"
    HYOPS_INSTALL_TX_HAD_PREVIOUS="true"
  fi
  mv "${HYOPS_INSTALL_TX_STAGE_PREFIX}" "${HYOPS_INSTALL_TX_FINAL_PREFIX}"
  HYOPS_INSTALL_TX_ACTIVATED="true"
  PREFIX="${HYOPS_INSTALL_TX_FINAL_PREFIX}"
  APP_DIR="${PREFIX}/app"
  VENV_DIR="${PREFIX}/venv"

  hyops_install_normalize_payload_permissions
  hyops_install_install_vault_helper

  hyops_install_install_user_wrapper
  hyops_install_install_system_link
  hyops_install_configure_macos_user_path
  hyops_install_verify_command
  hyops_install_run_setup_all

  HYOPS_INSTALL_TX_COMPLETED="true"
  rm -rf "${HYOPS_INSTALL_TX_PREVIOUS_PREFIX}"
  trap - EXIT HUP INT TERM
  echo "[install] OK"
  echo "Next:"
  echo "  hyops --help"
  if [[ "$(uname -s 2>/dev/null || true)" == "Darwin" ]]; then
    echo "  hyops setup base"
    echo "  hyops setup gcp"
    echo "  hyops setup galaxy"
  else
    echo "  hyops preflight"
  fi
  if [[ -n "${WRAPPER:-}" ]]; then
    echo "  ${WRAPPER} --help"
  fi
}
