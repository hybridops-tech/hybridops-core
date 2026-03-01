#!/usr/bin/env bash
# purpose: Install HybridOps.Core into a deterministic user prefix with a runnable `hyops` command.
# Architecture Decision: ADR-N/A (bootstrap installer)
# maintainer: HybridOps.Studio

set -euo pipefail
umask 077
chmod 0755 "$0" 2>/dev/null || true

usage() {
  cat <<'USAGE'
Usage:
  bash ./install.sh [--prefix <dir>] [--bin-dir <dir>] [--force] [--no-wrapper] [--no-system-link] [--setup-all|--no-setup-all]

Defaults:
  --prefix           ~/.hybridops/core
  --bin-dir          ~/.local/bin
  --system-link      enabled (installs /usr/local/bin/hyops; requires sudo)
  --setup-all        auto (runs when --system-link is enabled; use --no-setup-all to skip)
USAGE
}

PREFIX="${HOME}/.hybridops/core"
BIN_DIR="${HOME}/.local/bin"
FORCE="false"
NO_WRAPPER="false"
SYSTEM_LINK="true"
SETUP_ALL="auto"

while [[ $# -gt 0 ]]; do
  case "${1:-}" in
    --prefix) PREFIX="${2:-}"; shift 2 ;;
    --bin-dir) BIN_DIR="${2:-}"; shift 2 ;;
    --force) FORCE="true"; shift ;;
    --no-wrapper) NO_WRAPPER="true"; shift ;;
    --no-system-link) SYSTEM_LINK="false"; shift ;;
    --setup-all) SETUP_ALL="true"; shift ;;
    --no-setup-all) SETUP_ALL="false"; shift ;;
    -h|--help) usage; exit 0 ;;
    *) echo "ERR: unknown option: ${1}" >&2; usage; exit 2 ;;
  esac
done

need_cmd() { command -v "$1" >/dev/null 2>&1 || { echo "ERR: missing command: $1" >&2; exit 2; }; }

need_cmd python3
need_cmd cp
need_cmd mkdir
need_cmd find

set_blueprint_payload_read_only() {
  local root="$1"
  local bp_root="${root}/blueprints"
  [[ -d "${bp_root}" ]] || return 0

  find "${bp_root}" -type d -exec chmod 0755 {} +
  find "${bp_root}" -type f \( -name '*.yml' -o -name '*.yaml' \) -exec chmod 0444 {} +
}

SRC_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
PREFIX="$(python3 - <<PY
import os
print(os.path.abspath(os.path.expanduser("${PREFIX}")))
PY
)"
BIN_DIR="$(python3 - <<PY
import os
print(os.path.abspath(os.path.expanduser("${BIN_DIR}")))
PY
)"

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
  need_cmd sudo
  echo "[install] sudo required for /usr/local/bin/hyops"
  sudo -v || { echo "ERR: sudo cancelled; global hyops not installed" >&2; exit 3; }
fi

if [[ -d "${APP_DIR}" ]]; then
  if [[ "${FORCE}" == "true" ]]; then
    echo "[install] removing ${APP_DIR}"
    rm -rf "${APP_DIR}"
  else
    echo "ERR: app dir already exists: ${APP_DIR} (use --force)" >&2
    exit 2
  fi
fi

echo "[install] copying payload"
mkdir -p "${APP_DIR}"
cp -a "${SRC_ROOT}/." "${APP_DIR}/"
echo "[install] hardening shipped blueprint payload"
set_blueprint_payload_read_only "${APP_DIR}"

if [[ -d "${VENV_DIR}" ]]; then
  if [[ "${FORCE}" == "true" ]]; then
    echo "[install] removing ${VENV_DIR}"
    rm -rf "${VENV_DIR}"
  else
    echo "ERR: venv dir already exists: ${VENV_DIR} (use --force)" >&2
    exit 2
  fi
fi

echo "[install] creating venv"
if [[ "${USE_SYSTEM_DEPS}" == "true" ]]; then
  python3 -m venv --system-site-packages "${VENV_DIR}"
else
  python3 -m venv "${VENV_DIR}"
fi
if [[ "${INSTALL_NO_DEPS}" == "true" ]]; then
  echo "[install] installing source launcher without pip dependency resolution"
  cat >"${VENV_DIR}/bin/hyops" <<EOF
#!/usr/bin/env bash
set -euo pipefail

export PYTHONPATH="${APP_DIR}:${APP_DIR}/vendor/python\${PYTHONPATH:+:\${PYTHONPATH}}"
exec "${VENV_DIR}/bin/python3" -m hyops.cli "\$@"
EOF
  chmod 0755 "${VENV_DIR}/bin/hyops"
else
  WHEELHOUSE=""
  if [[ -n "${WHEELHOUSE_OVERRIDE}" ]]; then
    WHEELHOUSE="${WHEELHOUSE_OVERRIDE}"
  elif [[ -d "${APP_DIR}/wheels" ]]; then
    WHEELHOUSE="${APP_DIR}/wheels"
  fi

  if [[ -n "${WHEELHOUSE}" ]]; then
    if [[ ! -d "${WHEELHOUSE}" ]]; then
      echo "ERR: wheelhouse not found: ${WHEELHOUSE}" >&2
      exit 2
    fi
    echo "[install] installing from local wheelhouse"
    if [[ "${USE_SYSTEM_DEPS}" == "true" ]]; then
      "${VENV_DIR}/bin/python3" -m pip install --no-index --find-links "${WHEELHOUSE}" --no-deps hybridops-core >/dev/null
    else
      "${VENV_DIR}/bin/python3" -m pip install --no-index --find-links "${WHEELHOUSE}" hybridops-core >/dev/null
    fi
  else
    if [[ "${USE_SYSTEM_DEPS}" == "true" ]]; then
      "${VENV_DIR}/bin/python3" -m pip install --no-build-isolation --no-deps "${APP_DIR}" >/dev/null
    else
      "${VENV_DIR}/bin/python3" -m pip install -U pip >/dev/null
      "${VENV_DIR}/bin/python3" -m pip install "${APP_DIR}" >/dev/null
    fi
  fi
fi

echo "[install] normalizing installed payload permissions"
chmod -R a+rX "${PREFIX}"
set_blueprint_payload_read_only "${APP_DIR}"

if [[ -f "${VAULT_PASS_SRC}" ]]; then
  echo "[install] installing vault helper"
  cp -f "${VAULT_PASS_SRC}" "${VAULT_PASS_DST}"
  chmod 0755 "${VAULT_PASS_DST}"
fi

WRAPPER=""
if [[ "${NO_WRAPPER}" != "true" ]]; then
  echo "[install] writing user wrapper"
  mkdir -p "${BIN_DIR}"
  WRAPPER="${BIN_DIR}/hyops"

  cat >"${WRAPPER}" <<EOF
#!/usr/bin/env bash
set -euo pipefail

export HYOPS_CORE_ROOT="${APP_DIR}"
export HYOPS_VAULT_PASS_SCRIPT="${VAULT_PASS_DST}"
if [[ -d "${APP_DIR}/vendor/python" ]]; then
  export PYTHONPATH="${APP_DIR}/vendor/python\${PYTHONPATH:+:\${PYTHONPATH}}"
fi

exec "${VENV_DIR}/bin/hyops" "\$@"
EOF

  chmod 0755 "${WRAPPER}"
fi

if [[ "${SYSTEM_LINK}" == "true" ]]; then
  echo "[install] installing global hyops"
  sudo install -d -m 0755 /usr/local/bin
  sudo tee /usr/local/bin/hyops >/dev/null <<EOF
#!/usr/bin/env bash
set -euo pipefail

export HYOPS_CORE_ROOT="${APP_DIR}"
export HYOPS_VAULT_PASS_SCRIPT="${VAULT_PASS_DST}"
if [[ -d "${APP_DIR}/vendor/python" ]]; then
  export PYTHONPATH="${APP_DIR}/vendor/python\${PYTHONPATH:+:\${PYTHONPATH}}"
fi

exec "${VENV_DIR}/bin/hyops" "\$@"
EOF
  sudo chmod 0755 /usr/local/bin/hyops
fi

if [[ "${SETUP_ALL}" == "true" ]]; then
  SETUP_ALL_SCRIPT="${APP_DIR}/tools/setup/setup-all.sh"

  if [[ ! -f "${SETUP_ALL_SCRIPT}" ]]; then
    echo "ERR: setup-all not found: ${SETUP_ALL_SCRIPT}" >&2
    exit 2
  fi

  command -v sudo >/dev/null 2>&1 || { echo "ERR: sudo required for --setup-all"; exit 2; }

  echo "[install] running setup-all"
  sudo -E bash "${SETUP_ALL_SCRIPT}"
fi

echo "[install] OK"
echo "Try:"
echo "  hyops --help"
echo "  hyops preflight"
if [[ -n "${WRAPPER}" ]]; then
  echo "  ${WRAPPER} --help"
fi
