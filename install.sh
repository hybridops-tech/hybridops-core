#!/usr/bin/env bash
# purpose: Install HybridOps.Core into a deterministic user prefix with a runnable `hyops` command.
# Architecture Decision: ADR-N/A (bootstrap installer)
# maintainer: HybridOps.Tech

set -euo pipefail
umask 077
chmod 0755 "$0" 2>/dev/null || true

usage() {
  cat <<'USAGE'
Usage:
  ./install.sh [--prefix <dir>] [--bin-dir <dir>] [--force] [--no-wrapper] [--no-system-link] [--setup-all|--no-setup-all]

Defaults:
  --prefix           ~/.hybridops/core
  --bin-dir          ~/.local/bin
  --system-link      enabled (installs /usr/local/bin/hyops; requires sudo)
  --setup-all        auto (Linux: runs when --system-link is enabled; macOS: skipped)
USAGE
}

PREFIX="${HOME}/.hybridops/core"
BIN_DIR="${HOME}/.local/bin"
FORCE="false"
NO_WRAPPER="false"
SYSTEM_LINK="true"
SETUP_ALL="auto"
INSTALL_ORIGINAL_ARGV=("$@")

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

SRC_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
INSTALL_LIB="${SRC_ROOT}/tools/install/lib/installer.sh"

if [[ ! -f "${INSTALL_LIB}" ]]; then
  echo "ERR: installer library not found: ${INSTALL_LIB}" >&2
  exit 2
fi

# shellcheck source=/dev/null
source "${INSTALL_LIB}"

INSTALL_RUN_ID="install-$(date -u +%Y%m%dT%H%M%SZ)-$$"
INSTALL_EVIDENCE_DIR="${HOME}/.hybridops/logs/install/${INSTALL_RUN_ID}"
INSTALL_EVIDENCE_HELPER="${SRC_ROOT}/tools/install/install_evidence.py"
INSTALL_STARTED_AT="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
mkdir -p "${INSTALL_EVIDENCE_DIR}"
chmod 0700 "${INSTALL_EVIDENCE_DIR}"

_hyops_install_record_exit() {
  local rc="$?"
  trap - EXIT
  PYTHONPATH="${SRC_ROOT}${PYTHONPATH:+:${PYTHONPATH}}" python3 "${INSTALL_EVIDENCE_HELPER}" result \
    "${INSTALL_EVIDENCE_DIR}/result.json" "${INSTALL_STARTED_AT}" "${rc}" "$@" >/dev/null 2>&1 || true
  echo "run record: ${INSTALL_EVIDENCE_DIR}"
  exit "${rc}"
}

trap '_hyops_install_record_exit "${INSTALL_ORIGINAL_ARGV[@]}"' EXIT
exec > >(PYTHONPATH="${SRC_ROOT}${PYTHONPATH:+:${PYTHONPATH}}" python3 "${INSTALL_EVIDENCE_HELPER}" stream "${INSTALL_EVIDENCE_DIR}/output.log") 2>&1
hyops_install_run
