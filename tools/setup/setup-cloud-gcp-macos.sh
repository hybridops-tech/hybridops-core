#!/usr/bin/env bash
# purpose: Install Google Cloud CLI prerequisites on macOS with Homebrew.
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
  echo "ERR: Homebrew is required. Install it from https://brew.sh, then rerun: hyops setup gcp" >&2
  exit 2
}

progress "Installing Google Cloud support"
brew install --cask google-cloud-sdk

progress "Verifying Google Cloud support"
command -v gcloud >/dev/null 2>&1 || {
  echo "ERR: gcloud was installed but is not on PATH; start a new shell and retry" >&2
  exit 2
}

if ! command -v gke-gcloud-auth-plugin >/dev/null 2>&1; then
  gcloud components install gke-gcloud-auth-plugin --quiet || {
    echo "ERR: gke-gcloud-auth-plugin is unavailable; follow the Google Cloud CLI macOS component instructions" >&2
    exit 2
  }
fi

if ! command -v gke-gcloud-auth-plugin >/dev/null 2>&1; then
  sdk_root="$(gcloud info --format='value(installation.sdk_root)' 2>/dev/null || true)"
  plugin_path="${sdk_root}/bin/gke-gcloud-auth-plugin"
  brew_bin="$(brew --prefix)/bin"
  if [[ -x "${plugin_path}" ]]; then
    mkdir -p "${brew_bin}"
    ln -sf "${plugin_path}" "${brew_bin}/gke-gcloud-auth-plugin"
  fi
fi

command -v gke-gcloud-auth-plugin >/dev/null 2>&1 || {
  echo "ERR: gke-gcloud-auth-plugin was installed but is not available on PATH" >&2
  exit 2
}
gke-gcloud-auth-plugin --version >/dev/null 2>&1 || {
  echo "ERR: gke-gcloud-auth-plugin failed its version check" >&2
  exit 2
}

echo "[setup] gcloud installed"
echo "[setup] gke-gcloud-auth-plugin installed"
