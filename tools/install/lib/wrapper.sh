#!/usr/bin/env bash
# purpose: Wrapper/script generation helpers for installer.
# Architecture Decision: ADR-N/A (bootstrap installer)
# maintainer: HybridOps.Tech

hyops_install_write_wrapper() {
  local target_path="$1"

  cat >"${target_path}" <<EOS
#!/usr/bin/env bash
set -euo pipefail

export HYOPS_CORE_ROOT="${APP_DIR}"
export HYOPS_VAULT_PASS_SCRIPT="${VAULT_PASS_DST}"
if [[ -d "${APP_DIR}/vendor/python" ]]; then
  export PYTHONPATH="${APP_DIR}/vendor/python\${PYTHONPATH:+:\${PYTHONPATH}}"
fi

exec "${VENV_DIR}/bin/hyops" "\$@"
EOS

  chmod 0755 "${target_path}"
}

hyops_install_install_user_wrapper() {
  WRAPPER=""
  if [[ "${NO_WRAPPER}" != "true" ]]; then
    echo "[install] writing user wrapper"
    mkdir -p "${BIN_DIR}"
    WRAPPER="${BIN_DIR}/hyops"
    hyops_install_write_wrapper "${WRAPPER}"
  fi
}

hyops_install_install_system_link() {
  [[ "${SYSTEM_LINK}" == "true" ]] || return 0

  echo "[install] installing global hyops at ${SYSTEM_LINK_PATH}"

  if [[ "${EUID:-$(id -u)}" -eq 0 ]]; then
    install -d -m 0755 "${SYSTEM_LINK_DIR}"
    cat >"${SYSTEM_LINK_PATH}" <<EOS
#!/usr/bin/env bash
set -euo pipefail

export HYOPS_CORE_ROOT="${APP_DIR}"
export HYOPS_VAULT_PASS_SCRIPT="${VAULT_PASS_DST}"
if [[ -d "${APP_DIR}/vendor/python" ]]; then
  export PYTHONPATH="${APP_DIR}/vendor/python\${PYTHONPATH:+:\${PYTHONPATH}}"
fi

exec "${VENV_DIR}/bin/hyops" "\$@"
EOS
    chmod 0755 "${SYSTEM_LINK_PATH}"
    return 0
  fi

  sudo install -d -m 0755 "${SYSTEM_LINK_DIR}"
  sudo tee "${SYSTEM_LINK_PATH}" >/dev/null <<EOS
#!/usr/bin/env bash
set -euo pipefail

export HYOPS_CORE_ROOT="${APP_DIR}"
export HYOPS_VAULT_PASS_SCRIPT="${VAULT_PASS_DST}"
if [[ -d "${APP_DIR}/vendor/python" ]]; then
  export PYTHONPATH="${APP_DIR}/vendor/python\${PYTHONPATH:+:\${PYTHONPATH}}"
fi

exec "${VENV_DIR}/bin/hyops" "\$@"
EOS
  sudo chmod 0755 "${SYSTEM_LINK_PATH}"
}

hyops_install_path_contains_dir() {
  case ":${PATH}:" in
    *":$1:"*) return 0 ;;
    *) return 1 ;;
  esac
}

hyops_install_configure_macos_user_path() {
  PATH_PROFILE=""
  [[ "$(uname -s 2>/dev/null || true)" == "Darwin" ]] || return 0
  [[ -n "${WRAPPER:-}" ]] || return 0

  if [[ "${SYSTEM_LINK}" == "true" ]] && hyops_install_path_contains_dir "${SYSTEM_LINK_DIR}"; then
    return 0
  fi
  if hyops_install_path_contains_dir "${BIN_DIR}"; then
    return 0
  fi

  if [[ "${BIN_DIR}" != "${HOME}/.local/bin" ]]; then
    echo "WARN: ${BIN_DIR} is not on PATH; add it to your shell profile" >&2
    return 0
  fi

  PATH_PROFILE="${HOME}/.zprofile"
  local path_line='export PATH="$HOME/.local/bin:$PATH"'
  if [[ ! -f "${PATH_PROFILE}" ]] || ! grep -Fqx "${path_line}" "${PATH_PROFILE}"; then
    {
      echo ""
      echo "# HybridOps CLI"
      echo "${path_line}"
    } >>"${PATH_PROFILE}"
    echo "[install] added ${BIN_DIR} to ${PATH_PROFILE}"
  fi
}

hyops_install_verify_command() {
  local installed_command=""
  if [[ "${SYSTEM_LINK}" == "true" && -x "${SYSTEM_LINK_PATH}" ]]; then
    installed_command="${SYSTEM_LINK_PATH}"
  elif [[ -n "${WRAPPER:-}" && -x "${WRAPPER}" ]]; then
    installed_command="${WRAPPER}"
  fi

  [[ -n "${installed_command}" ]] || {
    echo "ERR: hyops command wrapper was not installed" >&2
    exit 2
  }
  "${installed_command}" --help >/dev/null || {
    echo "ERR: installed hyops command failed its verification check" >&2
    exit 2
  }
}
