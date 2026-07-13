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
  PATH="${PATH}:/usr/bin:/bin"
)

env HYOPS_TEST_SYSTEM_NAME=Linux WSL_DISTRO_NAME=Ubuntu bash -c \
  'source "$1"; hyops_install_is_windows_wsl' _ \
  "${HYOPS_REPO_ROOT}/tools/install/lib/common.sh"
env -u WSL_DISTRO_NAME -u WSL_INTEROP \
  HYOPS_TEST_SYSTEM_NAME=Linux \
  HYOPS_TEST_KERNEL_RELEASE=5.15.167.4-microsoft-standard-WSL2 \
  bash -c 'source "$1"; hyops_install_is_windows_wsl' _ \
  "${HYOPS_REPO_ROOT}/tools/install/lib/common.sh"
if env -u WSL_DISTRO_NAME -u WSL_INTEROP \
  HYOPS_TEST_SYSTEM_NAME=Linux \
  HYOPS_TEST_KERNEL_RELEASE=6.8.0-generic \
  bash -c 'source "$1"; hyops_install_is_windows_wsl' _ \
  "${HYOPS_REPO_ROOT}/tools/install/lib/common.sh"; then
  echo "ERR: plain Linux was detected as Windows WSL" >&2
  exit 1
fi

grep -Fq 'start "Ubuntu 24.04 account setup" wsl.exe -d %DISTRO%' "${HYOPS_REPO_ROOT}/install-windows.cmd"
grep -Fq ':wait_for_ubuntu_user' "${HYOPS_REPO_ROOT}/install-windows.cmd"
grep -Fq "CreateShortcut([Environment]::GetFolderPath('Desktop')" "${HYOPS_REPO_ROOT}/install-windows.cmd"
grep -Fq -- "-d %DISTRO% --cd ~" "${HYOPS_REPO_ROOT}/install-windows.cmd"
grep -Fq 'Create a HybridOps.Core desktop shortcut? [y/N]:' "${HYOPS_REPO_ROOT}/install-windows.cmd"
grep -Fq 'open-hybridops.cmd' "${HYOPS_REPO_ROOT}/pkg/build_release.sh"
grep -Fq -- '-u !WSL_USER! -- bash "%WSL_HELPER%"' "${HYOPS_REPO_ROOT}/install-windows.cmd"
grep -Fq -- '-u !WSL_USER! -- bash -lc "command -v hyops' "${HYOPS_REPO_ROOT}/install-windows.cmd"

latest_evidence_dir() {
  python3 - "$1" <<'PY'
import sys
from pathlib import Path

root = Path(sys.argv[1])
directories = [path for path in root.iterdir() if path.is_dir()]
if not directories:
    raise SystemExit(f"no evidence directories found under {root}")
print(max(directories, key=lambda path: path.stat().st_mtime_ns))
PY
}

env HOME="${USER_HOME}" "${common_env[@]}" \
  bash "${HYOPS_REPO_ROOT}/install.sh" --force --no-system-link --no-setup-all >/dev/null

if [[ "$(uname -s 2>/dev/null || true)" == "Darwin" ]]; then
  grep -Fqx 'export PATH="$HOME/.local/bin:$PATH"' "${USER_HOME}/.zprofile"
fi

env -u PYTHONPATH HOME="${USER_HOME}" "${USER_HOME}/.local/bin/hyops" --help >/dev/null
env -u PYTHONPATH HOME="${USER_HOME}" "${USER_HOME}/.local/bin/hyops" setup galaxy --help >/dev/null
env -u PYTHONPATH HOME="${USER_HOME}" "${USER_HOME}/.local/bin/hyops" setup galaxy --runtime-root "${USER_HOME}/.hybridops" --dry-run >/dev/null
# Compatibility alias remains available for existing runbooks.
env -u PYTHONPATH HOME="${USER_HOME}" "${USER_HOME}/.local/bin/hyops" setup ansible --help >/dev/null

INSTALL_EVIDENCE="$(latest_evidence_dir "${USER_HOME}/.hybridops/logs/install")"
python3 - "${INSTALL_EVIDENCE}" <<'PY'
import json
import os
from pathlib import Path
import stat
import sys

root = Path(sys.argv[1])
assert stat.S_IMODE(root.stat().st_mode) == 0o700
for name in ("output.log", "result.json"):
    path = root / name
    assert path.is_file()
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
result = json.loads((root / "result.json").read_text())
assert result["exit_code"] == 0
assert result["status"] == "ok"
PY

env -u PYTHONPATH HOME="${USER_HOME}" "${USER_HOME}/.local/bin/hyops" preflight >/dev/null
PREFLIGHT_EVIDENCE="$(latest_evidence_dir "${USER_HOME}/.hybridops/logs/preflight")"
python3 - "${PREFLIGHT_EVIDENCE}" <<'PY'
import json
from pathlib import Path
import stat
import sys

root = Path(sys.argv[1])
assert stat.S_IMODE(root.stat().st_mode) == 0o700
assert stat.S_IMODE((root / "output.log").stat().st_mode) == 0o600
assert json.loads((root / "result.json").read_text())["exit_code"] == 0
PY

set +e
env -u PYTHONPATH HOME="${USER_HOME}" "${USER_HOME}/.local/bin/hyops" setup check >"${WORK_DIR}/setup-check.out" 2>&1
SETUP_CHECK_RC=$?
set -e
SETUP_CHECK_EVIDENCE="$(latest_evidence_dir "${USER_HOME}/.hybridops/logs/setup/check")"
python3 - "${SETUP_CHECK_EVIDENCE}" "${SETUP_CHECK_RC}" <<'PY'
import json
from pathlib import Path
import stat
import sys

root = Path(sys.argv[1])
expected_rc = int(sys.argv[2])
assert stat.S_IMODE(root.stat().st_mode) == 0o700
assert stat.S_IMODE((root / "output.log").stat().st_mode) == 0o600
result = json.loads((root / "result.json").read_text())
assert result["exit_code"] == expected_rc
assert result["status"] == ("ok" if expected_rc == 0 else "failed")
PY

set +e
env -u PYTHONPATH HOME="${USER_HOME}" "${USER_HOME}/.local/bin/hyops" \
  preflight --target evidence-target-does-not-exist >"${WORK_DIR}/preflight-failure.out" 2>&1
PREFLIGHT_FAILURE_RC=$?
set -e
[[ "${PREFLIGHT_FAILURE_RC}" -ne 0 ]]
PREFLIGHT_FAILURE_EVIDENCE="$(latest_evidence_dir "${USER_HOME}/.hybridops/logs/preflight")"
python3 - "${PREFLIGHT_FAILURE_EVIDENCE}/result.json" "${PREFLIGHT_FAILURE_RC}" <<'PY'
import json
from pathlib import Path
import sys

result = json.loads(Path(sys.argv[1]).read_text())
assert result["exit_code"] == int(sys.argv[2])
assert result["status"] == "failed"
PY

env -u PYTHONPATH HOME="${USER_HOME}" "${USER_HOME}/.local/bin/hyops" \
  preflight --vault-password-command 'token=evidence-argv-secret' >/dev/null
PREFLIGHT_ARGV_EVIDENCE="$(latest_evidence_dir "${USER_HOME}/.hybridops/logs/preflight")"
! grep -Fq 'evidence-argv-secret' "${PREFLIGHT_ARGV_EVIDENCE}/result.json"
grep -Fq 'token=***REDACTED***' "${PREFLIGHT_ARGV_EVIDENCE}/result.json"

FAKE_SETUP_ROOT="${WORK_DIR}/fake-setup-core"
mkdir -p "${FAKE_SETUP_ROOT}/tools/setup"
cat >"${FAKE_SETUP_ROOT}/tools/setup/setup-base.sh" <<'EOF'
#!/usr/bin/env bash
echo "token=evidence-test-secret"
echo "expected setup failure"
exit 7
EOF
chmod 0755 "${FAKE_SETUP_ROOT}/tools/setup/setup-base.sh"
set +e
env -u PYTHONPATH HOME="${USER_HOME}" "${USER_HOME}/.local/bin/hyops" setup base --root "${FAKE_SETUP_ROOT}" >"${WORK_DIR}/setup-failure.out" 2>&1
SETUP_RC=$?
set -e
[[ "${SETUP_RC}" -eq 7 ]]
! grep -Fq 'evidence-test-secret' "${WORK_DIR}/setup-failure.out"
grep -Fq 'setup=base status=failed' "${WORK_DIR}/setup-failure.out"
grep -Fq 'rerun: hyops setup base --verbose' "${WORK_DIR}/setup-failure.out"
SETUP_EVIDENCE="$(latest_evidence_dir "${USER_HOME}/.hybridops/logs/setup/base")"
! grep -Fq 'evidence-test-secret' "${SETUP_EVIDENCE}/output.log"
grep -Fq 'token=***REDACTED***' "${SETUP_EVIDENCE}/output.log"
python3 - "${SETUP_EVIDENCE}/result.json" <<'PY'
import json
from pathlib import Path
import sys

result = json.loads(Path(sys.argv[1]).read_text())
assert result["exit_code"] == 7
assert result["status"] == "failed"
PY
env HOME="${USER_HOME}" "${common_env[@]}" \
  bash "${HYOPS_REPO_ROOT}/install.sh" --force --no-system-link --no-setup-all >/dev/null
if [[ "$(uname -s 2>/dev/null || true)" == "Darwin" ]]; then
  [[ "$(grep -Fxc 'export PATH="$HOME/.local/bin:$PATH"' "${USER_HOME}/.zprofile")" -eq 1 ]]
fi
env -u PYTHONPATH HOME="${USER_HOME}" "${USER_HOME}/.local/bin/hyops" show --help >/dev/null

# A failed replacement must leave the previous CLI usable and remove staging
# directories. Make the vault helper read-only to force a post-activation error.
cp "${USER_HOME}/.hybridops/core/app/install.sh" "${WORK_DIR}/installed-app.sh"
chmod 0555 "${USER_HOME}/.hybridops/tools" "${USER_HOME}/.hybridops/tools/vault-pass.sh"
if env HOME="${USER_HOME}" "${common_env[@]}" \
  bash "${HYOPS_REPO_ROOT}/install.sh" --force --no-system-link --no-setup-all >/dev/null 2>&1; then
  echo "ERR: installer rollback smoke did not trigger the expected failure" >&2
  exit 1
fi
chmod 0755 "${USER_HOME}/.hybridops/tools" "${USER_HOME}/.hybridops/tools/vault-pass.sh"
cmp "${WORK_DIR}/installed-app.sh" "${USER_HOME}/.hybridops/core/app/install.sh"
env -u PYTHONPATH HOME="${USER_HOME}" "${USER_HOME}/.local/bin/hyops" --help >/dev/null
test -z "$(find "${USER_HOME}/.hybridops" -maxdepth 1 \
  \( -name 'core.install.*' -o -name 'core.previous.*' \) -print -quit)"

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
  env -u PYTHONPATH HOME="${ROOT_HOME}" "${ROOT_BIN_DIR}/hyops" setup galaxy --help >/dev/null
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
  env -u PYTHONPATH HOME="${ROOT_HOME}" "${ROOT_BIN_DIR}/hyops" setup galaxy --runtime-root "${ROOT_HOME}/.hybridops" --dry-run >/dev/null

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
