#!/usr/bin/env bash
# purpose: Install Azure CLI prerequisites on macOS with Homebrew.
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
  echo "ERR: Homebrew is required. Install it from https://brew.sh, then rerun: hyops setup azure" >&2
  exit 2
}

progress "Installing Azure support"
brew install azure-cli
progress "Verifying Azure support"
command -v az >/dev/null 2>&1 || { echo "ERR: Azure CLI install failed" >&2; exit 1; }
echo "[setup] Azure CLI installed"
