#!/usr/bin/env bash
# purpose: Install base HybridOps prerequisites on macOS with Homebrew.
set -euo pipefail

if [[ "${EUID}" -eq 0 ]]; then
  echo "ERR: Homebrew setup must run as your macOS user (omit --sudo)" >&2
  exit 2
fi

command -v brew >/dev/null 2>&1 || {
  echo "ERR: Homebrew is required. Install it from https://brew.sh, then rerun: hyops setup base" >&2
  exit 2
}

echo "[setup] macOS Homebrew base prerequisites"
brew install python terraform terragrunt packer kubectl ansible pipx
echo "[setup] macOS base prerequisites installed"
