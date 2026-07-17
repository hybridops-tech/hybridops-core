#!/usr/bin/env bash
# purpose: Install base HybridOps prerequisites on macOS with Homebrew.
set -euo pipefail

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
progress "Preparing package repositories"
brew tap hashicorp/tap
progress "Installing infrastructure runtime"
brew install hashicorp/tap/terraform hashicorp/tap/packer
progress "Installing automation and vault support"
brew install python terragrunt kubectl ansible pipx gnupg pass pinentry-mac

progress "Verifying base setup"
for required_cmd in python3 terraform terragrunt packer kubectl ansible-playbook pipx gpg pass pinentry-mac; do
  command -v "${required_cmd}" >/dev/null 2>&1 || {
    echo "ERR: ${required_cmd} was installed but is not available on PATH" >&2
    exit 1
  }
done
echo "[setup] macOS base prerequisites installed"
