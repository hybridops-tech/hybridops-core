#!/usr/bin/env bash
# purpose: Python virtual environment and package install helpers for installer.
# Architecture Decision: ADR-N/A (bootstrap installer)
# maintainer: HybridOps.Tech

hyops_install_create_venv_and_payload() {
  echo "[install] creating venv"
  if [[ "${USE_SYSTEM_DEPS}" == "true" ]]; then
    python3 -m venv --system-site-packages "${VENV_DIR}"
  else
    python3 -m venv "${VENV_DIR}"
  fi

  if [[ "${INSTALL_NO_DEPS}" == "true" ]]; then
    echo "[install] installing source launcher without pip dependency resolution"
    cat >"${VENV_DIR}/bin/hyops" <<EOS
#!/usr/bin/env bash
set -euo pipefail

export PYTHONPATH="${APP_DIR}:${APP_DIR}/vendor/python\${PYTHONPATH:+:\${PYTHONPATH}}"
exec "${VENV_DIR}/bin/python3" -m hyops.cli "\$@"
EOS
    chmod 0755 "${VENV_DIR}/bin/hyops"
    return 0
  fi

  local wheelhouse=""
  if [[ -n "${WHEELHOUSE_OVERRIDE}" ]]; then
    wheelhouse="${WHEELHOUSE_OVERRIDE}"
  elif [[ -d "${APP_DIR}/wheels" ]]; then
    wheelhouse="${APP_DIR}/wheels"
  fi

  if [[ -n "${wheelhouse}" ]]; then
    if [[ ! -d "${wheelhouse}" ]]; then
      echo "ERR: wheelhouse not found: ${wheelhouse}" >&2
      exit 2
    fi
    echo "[install] installing from local wheelhouse"
    if [[ "${USE_SYSTEM_DEPS}" == "true" ]]; then
      "${VENV_DIR}/bin/python3" -m pip install --no-index --find-links "${wheelhouse}" --no-deps hybridops-core >/dev/null
    else
      "${VENV_DIR}/bin/python3" -m pip install --no-index --find-links "${wheelhouse}" hybridops-core >/dev/null
    fi
    return 0
  fi

  if [[ "${USE_SYSTEM_DEPS}" == "true" ]]; then
    "${VENV_DIR}/bin/python3" -m pip install --no-build-isolation --no-deps "${APP_DIR}" >/dev/null
  else
    "${VENV_DIR}/bin/python3" -m pip install -U pip >/dev/null
    "${VENV_DIR}/bin/python3" -m pip install "${APP_DIR}" >/dev/null
  fi
}
