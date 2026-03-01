#!/usr/bin/env bash
# purpose: Install all prerequisites for HybridOps.Core.
# Architecture Decision: ADR-N/A
# maintainer: HybridOps.Studio

set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"

FORCE_ARGS=()
while [[ $# -gt 0 ]]; do
  case "${1:-}" in
    --force)
      FORCE_ARGS=("--force")
      shift
      ;;
    -h|--help)
      echo "Usage: setup-all.sh [--force]"
      exit 0
      ;;
    *)
      echo "ERR: unknown option: ${1}" >&2
      exit 2
      ;;
  esac
done

if [[ "${EUID}" -ne 0 ]]; then
  exec sudo -E bash "$0" "$@"
fi

bash "${ROOT}/setup-base.sh"
bash "${ROOT}/setup-cloud-azure.sh"
bash "${ROOT}/setup-cloud-gcp.sh"

if [[ -n "${SUDO_USER:-}" && "${SUDO_USER}" != "root" ]]; then
  sudo -u "${SUDO_USER}" -E bash "${ROOT}/setup-ansible.sh"
fi