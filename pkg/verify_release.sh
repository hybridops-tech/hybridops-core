#!/usr/bin/env bash
# purpose: Verify a HybridOps.Core release bundle via isolated install and payload drift checks.
# adr: ADR-0622
# maintainer: HybridOps.Studio

set -euo pipefail

usage() {
  cat <<'USAGE'
Usage:
  bash pkg/verify_release.sh <bundle.tar.gz>

Environment:
  KEEP_WORKDIR=true   Keep the temporary verification workdir for inspection.
  HYOPS_RELEASE_VERIFY_USE_SYSTEM_DEPS=true
                      Reuse system site-packages during isolated install.
  HYOPS_RELEASE_VERIFY_NO_DEPS=true
                      Skip package installation and use the source launcher.
USAGE
}

if [[ $# -ne 1 ]]; then
  usage >&2
  exit 2
fi

_hyops_release_pkg_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"

# shellcheck source=/dev/null
source "${_hyops_release_pkg_dir}/lib/common.sh"

hyops_release_require_cmd tar
hyops_release_require_cmd sha256sum
hyops_release_require_cmd find
hyops_release_require_cmd mktemp

BUNDLE_PATH="$1"
if [[ ! -f "${BUNDLE_PATH}" ]]; then
  echo "ERR: bundle not found: ${BUNDLE_PATH}" >&2
  exit 2
fi

BUNDLE_PATH="$(cd -- "$(dirname -- "${BUNDLE_PATH}")" && pwd)/$(basename -- "${BUNDLE_PATH}")"
WORK_DIR="$(mktemp -d)"
EXTRACT_DIR="${WORK_DIR}/extract"
HOME_DIR="${WORK_DIR}/home"
INSTALL_ROOT="${HOME_DIR}/.hybridops/core"
INSTALLED_APP="${INSTALL_ROOT}/app"
INSTALLED_HYOPS="${HOME_DIR}/.local/bin/hyops"
BUNDLE_BYTES="$(stat -c %s "${BUNDLE_PATH}")"
REQUIRED_FREE_BYTES=$(( BUNDLE_BYTES * 20 ))
if (( REQUIRED_FREE_BYTES < 536870912 )); then
  REQUIRED_FREE_BYTES=536870912
fi

cleanup() {
  if [[ "${KEEP_WORKDIR:-false}" != "true" ]]; then
    rm -rf "${WORK_DIR}"
  fi
}
trap cleanup EXIT

hyops_release_assert_free_space "${WORK_DIR}" "${REQUIRED_FREE_BYTES}" \
  "free space or re-run with TMPDIR pointed at a larger filesystem"

mkdir -p "${EXTRACT_DIR}" "${HOME_DIR}"
tar -xzf "${BUNDLE_PATH}" -C "${EXTRACT_DIR}"

mapfile -t extracted_roots < <(find "${EXTRACT_DIR}" -mindepth 1 -maxdepth 1 -type d | sort)
if [[ "${#extracted_roots[@]}" -ne 1 ]]; then
  echo "ERR: expected exactly one extracted bundle root, found ${#extracted_roots[@]}" >&2
  exit 3
fi

RELEASE_ROOT="${extracted_roots[0]}"
if [[ ! -f "${RELEASE_ROOT}/pkg/release-files.sha256" ]]; then
  echo "ERR: release checksum manifest missing from extracted bundle" >&2
  exit 3
fi

(
  cd "${RELEASE_ROOT}"
  sha256sum -c pkg/release-files.sha256 >/dev/null
)

install_env=(HOME="${HOME_DIR}" PATH="/usr/bin:/bin:${PATH}")
if [[ "${HYOPS_RELEASE_VERIFY_USE_SYSTEM_DEPS:-false}" == "true" ]]; then
  install_env+=(HYOPS_INSTALL_USE_SYSTEM_DEPS=true)
fi
if [[ "${HYOPS_RELEASE_VERIFY_NO_DEPS:-false}" == "true" ]]; then
  install_env+=(HYOPS_INSTALL_NO_DEPS=true)
fi

env "${install_env[@]}" \
  bash "${RELEASE_ROOT}/install.sh" --force --no-system-link --no-setup-all >/dev/null

if [[ ! -x "${INSTALLED_HYOPS}" ]]; then
  echo "ERR: installed hyops wrapper missing: ${INSTALLED_HYOPS}" >&2
  exit 3
fi
if [[ ! -d "${INSTALLED_APP}" ]]; then
  echo "ERR: installed app payload missing: ${INSTALLED_APP}" >&2
  exit 3
fi

(
  cd /
  env -u PYTHONPATH HOME="${HOME_DIR}" "${INSTALLED_HYOPS}" --help >/dev/null
  env -u PYTHONPATH HOME="${HOME_DIR}" "${INSTALLED_HYOPS}" preflight --help >/dev/null
  env -u PYTHONPATH HOME="${HOME_DIR}" "${INSTALLED_HYOPS}" init --help >/dev/null
)

(
  cd "${INSTALLED_APP}"
  sha256sum -c pkg/release-files.sha256 >/dev/null
)

echo "Verified bundle:"
echo "  ${BUNDLE_PATH}"
echo "Installed runtime root:"
echo "  ${INSTALL_ROOT}"
if [[ "${KEEP_WORKDIR:-false}" == "true" ]]; then
  echo "Verification workdir:"
  echo "  ${WORK_DIR}"
fi
