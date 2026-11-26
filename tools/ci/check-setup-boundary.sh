#!/usr/bin/env bash
# purpose: Verify the operator-supplied executor boundary in base setup.
# adr: ADR-N/A
# maintainer: HybridOps.Tech

set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd -- "${SCRIPT_DIR}/../.." && pwd)"
LINUX_SETUP="${REPO_ROOT}/tools/setup/setup-base.sh"
MACOS_SETUP="${REPO_ROOT}/tools/setup/setup-base-macos.sh"
SETUP_ROOT="${REPO_ROOT}/tools/setup"

if grep -Eq \
  'releases\.hashicorp\.com/(terraform|packer)|hashicorp/tap|(pip|pipx).*install.*(ansible|ansible-core)|(apt-get|dnf|yum|brew).*install.*(terraform|packer|ansible)' \
  "${LINUX_SETUP}" "${MACOS_SETUP}" "${SETUP_ROOT}/lib/"*.sh; then
  echo "ERR: base setup installs an operator-supplied executor" >&2
  exit 1
fi
