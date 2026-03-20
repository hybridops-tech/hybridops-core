#!/usr/bin/env bash
# purpose: Smoke test HybridOps installer in both user and root-safe system-link modes.
# adr: ADR-0622
# maintainer: HybridOps.Tech

set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=/dev/null
source "${SCRIPT_DIR}/lib/common.sh"

hyops_ci::require_cmd bash
hyops_ci::require_cmd mktemp
hyops_ci::require_cmd python3

WORK_DIR="$(mktemp -d)"
cleanup() {
  if sudo -n true >/dev/null 2>&1; then
    sudo rm -rf "${WORK_DIR}" 2>/dev/null || true
  fi
  rm -rf "${WORK_DIR}"
}
trap cleanup EXIT

USER_HOME="${WORK_DIR}/user-home"
ROOT_SHARED="${WORK_DIR}/root-shared"
ROOT_HOME="${ROOT_SHARED}/home"
ROOT_PREFIX="${ROOT_SHARED}/prefix"
ROOT_BIN_DIR="${ROOT_SHARED}/bin"
ROOT_USER_BIN="${ROOT_SHARED}/user-bin"
ROOT_CACHE_DIR="${ROOT_SHARED}/pip-cache"
ROOT_FAKE_APP="${ROOT_SHARED}/fake-app"
ROOT_SETUP_MARKER="${ROOT_SHARED}/setup-all-marker.txt"
mkdir -p "${USER_HOME}" "${ROOT_SHARED}" "${ROOT_HOME}" "${ROOT_PREFIX}" "${ROOT_BIN_DIR}" "${ROOT_USER_BIN}" "${ROOT_CACHE_DIR}" "${ROOT_FAKE_APP}/tools/setup"
chmod 0755 "${ROOT_SHARED}" "${ROOT_HOME}" "${ROOT_PREFIX}" "${ROOT_BIN_DIR}" "${ROOT_USER_BIN}" "${ROOT_CACHE_DIR}" "${ROOT_FAKE_APP}" "${ROOT_FAKE_APP}/tools" "${ROOT_FAKE_APP}/tools/setup"

common_env=(
  PATH="/usr/bin:/bin:${PATH}"
  HYOPS_INSTALL_USE_SYSTEM_DEPS=true
)

env HOME="${USER_HOME}" "${common_env[@]}" \
  bash "${HYOPS_REPO_ROOT}/install.sh" --force --no-system-link --no-setup-all >/dev/null

env -u PYTHONPATH HOME="${USER_HOME}" "${USER_HOME}/.local/bin/hyops" --help >/dev/null
env -u PYTHONPATH HOME="${USER_HOME}" "${USER_HOME}/.local/bin/hyops" setup ansible --help >/dev/null
env -u PYTHONPATH HOME="${USER_HOME}" "${USER_HOME}/.local/bin/hyops" setup ansible --runtime-root "${USER_HOME}/.hybridops" --dry-run >/dev/null
env HOME="${USER_HOME}" "${common_env[@]}" \
  bash "${HYOPS_REPO_ROOT}/install.sh" --force --no-system-link --no-setup-all >/dev/null
env -u PYTHONPATH HOME="${USER_HOME}" "${USER_HOME}/.local/bin/hyops" show --help >/dev/null

if sudo -n true >/dev/null 2>&1; then
  sudo install -d -m 0755 "${ROOT_CACHE_DIR}"
  sudo env HOME="${ROOT_HOME}" "${common_env[@]}" \
    PIP_CACHE_DIR="${ROOT_CACHE_DIR}" \
    HYOPS_INSTALL_SYSTEM_LINK_PATH="${ROOT_BIN_DIR}/hyops" \
    bash "${HYOPS_REPO_ROOT}/install.sh" \
      --prefix "${ROOT_PREFIX}" \
      --bin-dir "${ROOT_USER_BIN}" \
      --force \
      --no-wrapper \
      --no-setup-all >/dev/null

  env -u PYTHONPATH HOME="${ROOT_HOME}" "${ROOT_BIN_DIR}/hyops" --help >/dev/null
  env -u PYTHONPATH HOME="${ROOT_HOME}" "${ROOT_BIN_DIR}/hyops" setup ansible --help >/dev/null
  sudo env HOME="${ROOT_HOME}" "${common_env[@]}" \
    PIP_CACHE_DIR="${ROOT_CACHE_DIR}" \
    HYOPS_INSTALL_SYSTEM_LINK_PATH="${ROOT_BIN_DIR}/hyops" \
    bash "${HYOPS_REPO_ROOT}/install.sh" \
      --prefix "${ROOT_PREFIX}" \
      --bin-dir "${ROOT_USER_BIN}" \
      --force \
      --no-wrapper \
      --no-setup-all >/dev/null
  env -u PYTHONPATH HOME="${ROOT_HOME}" "${ROOT_BIN_DIR}/hyops" show --help >/dev/null
  env -u PYTHONPATH HOME="${ROOT_HOME}" "${ROOT_BIN_DIR}/hyops" setup ansible --runtime-root "${ROOT_HOME}/.hybridops" --dry-run >/dev/null

  cat > "${ROOT_FAKE_APP}/tools/setup/setup-all.sh" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
printf 'root=%s\n' "$(id -u)" > "${APP_MARKER}"
EOF
  chmod 0755 "${ROOT_FAKE_APP}/tools/setup/setup-all.sh"

  sudo env APP_DIR="${ROOT_FAKE_APP}" SETUP_ALL=true APP_MARKER="${ROOT_SETUP_MARKER}" bash -s >/dev/null <<EOF
sudo() {
  echo "unexpected sudo invocation from root setup-all smoke" >&2
  return 99
}
source "${HYOPS_REPO_ROOT}/tools/install/lib/setup.sh"
hyops_install_run_setup_all
EOF

  grep -qx 'root=0' "${ROOT_SETUP_MARKER}"
else
  echo "WARN: skipping root install smoke; passwordless sudo unavailable" >&2
fi
