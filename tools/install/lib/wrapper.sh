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

  echo "[install] installing global hyops"
  sudo install -d -m 0755 /usr/local/bin
  sudo tee /usr/local/bin/hyops >/dev/null <<EOS
#!/usr/bin/env bash
set -euo pipefail

export HYOPS_CORE_ROOT="${APP_DIR}"
export HYOPS_VAULT_PASS_SCRIPT="${VAULT_PASS_DST}"
if [[ -d "${APP_DIR}/vendor/python" ]]; then
  export PYTHONPATH="${APP_DIR}/vendor/python\${PYTHONPATH:+:\${PYTHONPATH}}"
fi

exec "${VENV_DIR}/bin/hyops" "\$@"
EOS
  sudo chmod 0755 /usr/local/bin/hyops
}
