#!/usr/bin/env bash
# purpose: Verify a HybridOps.Core release bundle via isolated install and payload drift checks.
# adr: ADR-0622
# maintainer: HybridOps.Tech

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
ROOT_HOME_DIR="${WORK_DIR}/root-home"
ROOT_LINK_DIR="${WORK_DIR}/root-bin"
ROOT_LINK_HYOPS="${ROOT_LINK_DIR}/hyops"
BUNDLE_BYTES="$(stat -c %s "${BUNDLE_PATH}")"
REQUIRED_FREE_BYTES=$(( BUNDLE_BYTES * 20 ))
if (( REQUIRED_FREE_BYTES < 536870912 )); then
  REQUIRED_FREE_BYTES=536870912
fi

cleanup() {
  if [[ "${KEEP_WORKDIR:-false}" != "true" ]]; then
    if sudo -n true >/dev/null 2>&1; then
      sudo rm -rf "${WORK_DIR}" 2>/dev/null || true
    fi
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

env "${install_env[@]}" \
  bash "${RELEASE_ROOT}/install.sh" --force --no-system-link --no-setup-all >/dev/null
(
  cd /
  env -u PYTHONPATH HOME="${HOME_DIR}" "${INSTALLED_HYOPS}" show --help >/dev/null
)

(
  cd "${INSTALLED_APP}"
  sha256sum -c pkg/release-files.sha256 >/dev/null
)

if sudo -n true >/dev/null 2>&1; then
  ROOT_SHARED_DIR="${WORK_DIR}/root-shared"
  ROOT_PREFIX_DIR="${ROOT_SHARED_DIR}/prefix"
  ROOT_USER_BIN_DIR="${ROOT_SHARED_DIR}/user-bin"
  ROOT_CACHE_DIR="${ROOT_SHARED_DIR}/pip-cache"
  ROOT_FAKE_APP_DIR="${ROOT_SHARED_DIR}/fake-app"
  ROOT_SETUP_MARKER="${ROOT_SHARED_DIR}/setup-all-marker.txt"

  mkdir -p "${ROOT_SHARED_DIR}" "${ROOT_HOME_DIR}" "${ROOT_LINK_DIR}" "${ROOT_PREFIX_DIR}" "${ROOT_USER_BIN_DIR}" "${ROOT_CACHE_DIR}" "${ROOT_FAKE_APP_DIR}/tools/setup"
  chmod 0755 "${ROOT_SHARED_DIR}" "${ROOT_HOME_DIR}" "${ROOT_LINK_DIR}" "${ROOT_PREFIX_DIR}" "${ROOT_USER_BIN_DIR}" "${ROOT_CACHE_DIR}" "${ROOT_FAKE_APP_DIR}" "${ROOT_FAKE_APP_DIR}/tools" "${ROOT_FAKE_APP_DIR}/tools/setup"
  sudo install -d -m 0755 "${ROOT_CACHE_DIR}"

  sudo env HOME="${ROOT_HOME_DIR}" PATH="/usr/bin:/bin:${PATH}" \
    HYOPS_INSTALL_SYSTEM_LINK_PATH="${ROOT_LINK_HYOPS}" \
    HYOPS_INSTALL_USE_SYSTEM_DEPS=true \
    PIP_CACHE_DIR="${ROOT_CACHE_DIR}" \
    bash "${RELEASE_ROOT}/install.sh" \
      --prefix "${ROOT_PREFIX_DIR}" \
      --bin-dir "${ROOT_USER_BIN_DIR}" \
      --force \
      --no-wrapper \
      --no-setup-all >/dev/null

  env -u PYTHONPATH HOME="${ROOT_HOME_DIR}" "${ROOT_LINK_HYOPS}" --help >/dev/null
  sudo env HOME="${ROOT_HOME_DIR}" PATH="/usr/bin:/bin:${PATH}" \
    HYOPS_INSTALL_SYSTEM_LINK_PATH="${ROOT_LINK_HYOPS}" \
    HYOPS_INSTALL_USE_SYSTEM_DEPS=true \
    PIP_CACHE_DIR="${ROOT_CACHE_DIR}" \
    bash "${RELEASE_ROOT}/install.sh" \
      --prefix "${ROOT_PREFIX_DIR}" \
      --bin-dir "${ROOT_USER_BIN_DIR}" \
      --force \
      --no-wrapper \
      --no-setup-all >/dev/null
  env -u PYTHONPATH HOME="${ROOT_HOME_DIR}" "${ROOT_LINK_HYOPS}" show --help >/dev/null

  cat > "${ROOT_FAKE_APP_DIR}/tools/setup/setup-all.sh" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
printf 'root=%s\n' "$(id -u)" > "${APP_MARKER}"
EOF
  chmod 0755 "${ROOT_FAKE_APP_DIR}/tools/setup/setup-all.sh"

  sudo env APP_DIR="${ROOT_FAKE_APP_DIR}" SETUP_ALL=true APP_MARKER="${ROOT_SETUP_MARKER}" bash -s >/dev/null <<EOF
sudo() {
  echo "unexpected sudo invocation from root setup-all smoke" >&2
  return 99
}
source "${RELEASE_ROOT}/tools/install/lib/setup.sh"
hyops_install_run_setup_all
EOF

  grep -qx 'root=0' "${ROOT_SETUP_MARKER}"
fi

echo "Verified bundle:"
echo "  ${BUNDLE_PATH}"
echo "Installed runtime root:"
echo "  ${INSTALL_ROOT}"
if [[ "${KEEP_WORKDIR:-false}" == "true" ]]; then
  echo "Verification workdir:"
  echo "  ${WORK_DIR}"
fi
