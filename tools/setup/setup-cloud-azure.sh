#!/usr/bin/env bash
# purpose: Install Azure CLI prerequisites for HybridOps.Core.
# architecture decision: ADR-N/A
# maintainer: HybridOps.Studio

set -euo pipefail

command -v az >/dev/null 2>&1 && { echo "[setup] azure-cli present"; exit 0; }

[[ "${EUID}" -eq 0 ]] || { echo "ERR: requires root (use: hyops setup cloud-azure --sudo)"; exit 2; }

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
RELEASE_ROOT="$(cd -- "${SCRIPT_DIR}/../.." && pwd)"

# shellcheck source=/dev/null
source "${RELEASE_ROOT}/tools/setup/lib/toolchain_lock.sh"

apt-get update -y
apt-get install -y ca-certificates curl gnupg lsb-release

install -d -m 0755 /etc/apt/keyrings

if [[ ! -f /etc/apt/keyrings/microsoft.gpg ]]; then
  curl -fsSL https://packages.microsoft.com/keys/microsoft.asc \
    | gpg --dearmor -o /etc/apt/keyrings/microsoft.gpg
fi

dist="$(. /etc/os-release && echo "${VERSION_CODENAME}")"
cat >/etc/apt/sources.list.d/azure-cli.list <<EOF
deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/microsoft.gpg] https://packages.microsoft.com/repos/azure-cli/ ${dist} main
EOF

apt-get update -y

az_ver="$(toolchain_get AZ_CLI_VERSION)"
if [[ -n "${az_ver}" ]]; then
  apt-get install -y "azure-cli=${az_ver}" || {
    echo "ERR: failed to install pinned azure-cli version: ${az_ver}" >&2
    echo "ERR: set AZ_CLI_VERSION blank in toolchain.lock or provide a valid apt version string." >&2
    exit 2
  }
else
  apt-get install -y azure-cli
fi

command -v az >/dev/null 2>&1 || { echo "ERR: az install failed"; exit 1; }

echo "[setup] azure-cli installed"