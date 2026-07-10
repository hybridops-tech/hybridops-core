#!/usr/bin/env bash
# purpose: Install Google Cloud CLI prerequisites on macOS with Homebrew.
set -euo pipefail

if [[ "${EUID}" -eq 0 ]]; then
  echo "ERR: Homebrew setup must run as your macOS user (omit --sudo)" >&2
  exit 2
fi

command -v brew >/dev/null 2>&1 || {
  echo "ERR: Homebrew is required. Install it from https://brew.sh, then rerun: hyops setup gcp" >&2
  exit 2
}

brew install --cask google-cloud-sdk

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

echo "[setup] gcloud installed"
echo "[setup] gke-gcloud-auth-plugin installed"
