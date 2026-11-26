#!/usr/bin/env bash
# purpose: Install base HybridOps prerequisites on macOS with Homebrew.
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
RELEASE_ROOT="$(cd -- "${SCRIPT_DIR}/../.." && pwd)"

# shellcheck source=/dev/null
source "${RELEASE_ROOT}/tools/setup/lib/toolchain_lock.sh"
# shellcheck source=/dev/null
source "${RELEASE_ROOT}/tools/setup/lib/external_executors.sh"

progress() {
  echo "[hyops-progress] $1"
}

progress "Checking Homebrew"
if [[ "${EUID}" -eq 0 ]]; then
  echo "ERR: Homebrew setup must run as your macOS user (omit --sudo)" >&2
  exit 2
fi

command -v brew >/dev/null 2>&1 || {
  echo "ERR: Homebrew is required. Install it from https://brew.sh, then rerun: hyops setup base" >&2
  exit 2
}

echo "[setup] macOS Homebrew base prerequisites"
toolchain__load
progress "Installing managed runtime"
brew install python terragrunt kubectl
progress "Installing vault support"
brew install gnupg pass pinentry-mac

progress "Checking external executors"
hyops_setup_verify_external_executors \
  "${TERRAFORM_VERSION}" "${PACKER_VERSION}" "${ANSIBLE_CORE_VERSION}"

progress "Verifying base setup"
for required_cmd in python3 terragrunt kubectl gpg pass pinentry-mac; do
  command -v "${required_cmd}" >/dev/null 2>&1 || {
    echo "ERR: ${required_cmd} was installed but is not available on PATH" >&2
    exit 1
  }
done
echo "[setup] macOS base ready"
