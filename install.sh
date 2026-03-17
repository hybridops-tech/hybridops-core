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

SRC_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
INSTALL_LIB="${SRC_ROOT}/tools/install/lib/installer.sh"

if [[ ! -f "${INSTALL_LIB}" ]]; then
  echo "ERR: installer library not found: ${INSTALL_LIB}" >&2
  exit 2
fi

# shellcheck source=/dev/null
source "${INSTALL_LIB}"
hyops_install_run
