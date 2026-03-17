#!/usr/bin/env bash
# purpose: Install Google Cloud SDK prerequisites for HybridOps.Core.
# architecture decision: ADR-N/A
# maintainer: HybridOps.Tech

set -euo pipefail

have_gcloud=false
have_gke_auth_plugin=false

command -v gcloud >/dev/null 2>&1 && have_gcloud=true
command -v gke-gcloud-auth-plugin >/dev/null 2>&1 && have_gke_auth_plugin=true

if [[ "${have_gcloud}" == true && "${have_gke_auth_plugin}" == true ]]; then
  echo "[setup] gcloud present"
  echo "[setup] gke-gcloud-auth-plugin present"
  exit 0
fi

[[ "${EUID}" -eq 0 ]] || { echo "ERR: requires root (use: hyops setup cloud-gcp --sudo)"; exit 2; }

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
RELEASE_ROOT="$(cd -- "${SCRIPT_DIR}/../.." && pwd)"

# shellcheck source=/dev/null
source "${RELEASE_ROOT}/tools/setup/lib/toolchain_lock.sh"

apt-get update -y
apt-get install -y ca-certificates curl gnupg

install -d -m 0755 /usr/share/keyrings

if [[ ! -f /usr/share/keyrings/cloud.google.gpg ]]; then
  curl -fsSL https://packages.cloud.google.com/apt/doc/apt-key.gpg \
    | gpg --dearmor -o /usr/share/keyrings/cloud.google.gpg
fi

cat >/etc/apt/sources.list.d/google-cloud-sdk.list <<'EOF'
deb [signed-by=/usr/share/keyrings/cloud.google.gpg] https://packages.cloud.google.com/apt cloud-sdk main
EOF

apt-get update -y

if [[ "${have_gcloud}" != true ]]; then
  gcloud_ver="$(toolchain_get GCLOUD_CLI_VERSION)"
  if [[ -n "${gcloud_ver}" ]]; then
    # Distro-specific apt version strings may be required.
    apt-get install -y "google-cloud-cli=${gcloud_ver}" || {
      echo "ERR: failed to install pinned google-cloud-cli version: ${gcloud_ver}" >&2
      echo "ERR: set GCLOUD_CLI_VERSION blank in toolchain.lock or provide a valid apt version string." >&2
      exit 2
    }
  else
    apt-get install -y google-cloud-cli || apt-get install -y google-cloud-sdk
  fi
fi

if [[ "${have_gke_auth_plugin}" != true ]]; then
  apt-get install -y google-cloud-cli-gke-gcloud-auth-plugin \
    || apt-get install -y google-cloud-sdk-gke-gcloud-auth-plugin
fi

command -v gcloud >/dev/null 2>&1 || { echo "ERR: gcloud install failed"; exit 1; }
command -v gke-gcloud-auth-plugin >/dev/null 2>&1 || { echo "ERR: gke-gcloud-auth-plugin install failed"; exit 1; }

echo "[setup] gcloud installed"
echo "[setup] gke-gcloud-auth-plugin installed"
