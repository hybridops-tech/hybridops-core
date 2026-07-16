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

WINDOWS_INSTALLER="${HYOPS_REPO_ROOT}/tools/install/windows/install-windows.cmd"
grep -Fq 'set /p "NEW_WSL_USER=Ubuntu username: "' "${WINDOWS_INSTALLER}"
grep -Fq -- "-cmatch '^[a-z_][a-z0-9_-]{0,31}$'" "${WINDOWS_INSTALLER}"
grep -Fq -- 'useradd --create-home --shell /bin/bash --uid 1000' "${WINDOWS_INSTALLER}"
grep -Fq -- 'passwd !NEW_WSL_USER!' "${WINDOWS_INSTALLER}"
grep -Fq -- 'usermod --append --groups sudo' "${WINDOWS_INSTALLER}"
grep -Fq "default=!NEW_WSL_USER!" "${WINDOWS_INSTALLER}"
if grep -Fq 'start "Ubuntu 24.04 account setup"' "${WINDOWS_INSTALLER}"; then
  echo "ERR: Windows installer opens a separate Ubuntu account window" >&2
  exit 1
fi
grep -Fq "CreateShortcut([Environment]::GetFolderPath('Desktop')" "${WINDOWS_INSTALLER}"
grep -Fq -- "-d %DISTRO% --cd ~" "${WINDOWS_INSTALLER}"
grep -Fq "LOCALAPPDATA 'HybridOps'" "${WINDOWS_INSTALLER}"
grep -Fq 'set "PAYLOAD_DIR=%~dp0payload"' "${WINDOWS_INSTALLER}"
grep -Fq 'set "ARCHIVE=%PAYLOAD_DIR%\hybridops-core.tar.gz"' "${WINDOWS_INSTALLER}"
grep -Fq 'set "HELPER=%PAYLOAD_DIR%\install-wsl.sh"' "${WINDOWS_INSTALLER}"
grep -Fq "Copy-Item -Force -LiteralPath '%PAYLOAD_DIR%\hybridops.ico'" "${WINDOWS_INSTALLER}"
grep -Fq 'Create a HybridOps.Core desktop shortcut? [y/N]:' "${WINDOWS_INSTALLER}"
grep -Fq 'Windows must restart before %DISTRO% can finish registration.' "${WINDOWS_INSTALLER}"
grep -Fq 'set /p "RESTART_NOW=Restart Windows now? [y/N]: "' "${WINDOWS_INSTALLER}"
grep -Fq 'Install HybridOps.cmd' "${HYOPS_REPO_ROOT}/pkg/build_release.sh"
grep -Fq 'WINDOWS_PAYLOAD_STAGE' "${HYOPS_REPO_ROOT}/pkg/build_release.sh"
grep -Fq 'line.strip() == "---"' "${HYOPS_REPO_ROOT}/pkg/build_release.sh"
grep -Fq 'line.startswith("# ")' "${HYOPS_REPO_ROOT}/pkg/build_release.sh"
if grep -Fq 'open-hybridops.cmd' "${HYOPS_REPO_ROOT}/pkg/build_release.sh"; then
  echo "ERR: Windows bundle exposes a launcher before installation" >&2
  exit 1
fi
grep -Fq 'assets/windows/hybridops.ico' "${HYOPS_REPO_ROOT}/pkg/build_release.sh"
test -s "${HYOPS_REPO_ROOT}/assets/windows/hybridops.ico"
grep -Fq -- '-u !WSL_USER! -- bash "%WSL_HELPER%"' "${WINDOWS_INSTALLER}"
grep -Fq -- '-u !WSL_USER! -- bash -lc "command -v hyops' "${WINDOWS_INSTALLER}"
grep -Fq 'Support: https://github.com/hybridops-tech/hybridops-core/discussions' \
  "${HYOPS_REPO_ROOT}/tools/install/lib/installer.sh"
grep -Fq 'Sponsor: https://github.com/sponsors/hybridops-tech' \
  "${HYOPS_REPO_ROOT}/tools/install/lib/installer.sh"
if grep -Eq 'echo "(Project|Discuss):' "${HYOPS_REPO_ROOT}/tools/install/lib/installer.sh"; then
  echo "ERR: installer completion output contains a redundant project link" >&2
  exit 1
fi

bash -n "${HYOPS_REPO_ROOT}/pkg/build_macos_pkg.sh"
bash -n "${HYOPS_REPO_ROOT}/pkg/build_release.sh"
bash -n "${HYOPS_REPO_ROOT}/pkg/macos/preinstall"
bash -n "${HYOPS_REPO_ROOT}/pkg/macos/postinstall"
sh -n "${HYOPS_REPO_ROOT}/pkg/macos/uninstall-macos.sh"
grep -Fq -- '--no-system-link --no-setup-all' "${HYOPS_REPO_ROOT}/pkg/macos/postinstall"
grep -Fq 'Python 3.11 or newer' "${HYOPS_REPO_ROOT}/pkg/macos/preinstall"
grep -Fq 'macOS 13 or newer' "${HYOPS_REPO_ROOT}/pkg/macos/preinstall"
grep -Fq 'hybridops-core/discussions' "${HYOPS_REPO_ROOT}/pkg/macos/preinstall"
grep -Fq 'HYOPS_RELEASE_VERSION=' "${HYOPS_REPO_ROOT}/pkg/build_release.sh"
grep -Fq 'does not match release version' "${HYOPS_REPO_ROOT}/pkg/verify_release.sh"
grep -Fq 'HybridOps.Core macOS package launcher' "${HYOPS_REPO_ROOT}/pkg/macos/postinstall"
grep -Fq '/Library/Logs/HybridOps' "${HYOPS_REPO_ROOT}/pkg/macos/postinstall"
grep -Fq '[1/4] Verifying the release package' "${HYOPS_REPO_ROOT}/pkg/macos/postinstall"
grep -Fq 'Window → Installer Log' "${HYOPS_REPO_ROOT}/pkg/macos/resources/welcome.html"
grep -Fq 'font-family: -apple-system' "${HYOPS_REPO_ROOT}/pkg/macos/resources/welcome.html"
grep -Fq 'src="hybridops.svg"' "${HYOPS_REPO_ROOT}/pkg/macos/resources/welcome.html"
grep -Fq 'src="hybridops.svg"' "${HYOPS_REPO_ROOT}/pkg/macos/resources/conclusion.html"
test -s "${HYOPS_REPO_ROOT}/pkg/macos/resources/hybridops.svg"
grep -Fq 'resources/hybridops.svg' "${HYOPS_REPO_ROOT}/pkg/build_macos_pkg.sh"
grep -Fq 'Open installation log' "${HYOPS_REPO_ROOT}/pkg/macos/resources/conclusion.html"
grep -Fq 'file:///System/Applications/Utilities/Terminal.app' \
  "${HYOPS_REPO_ROOT}/pkg/macos/resources/conclusion.html"
grep -Fq 'file:///Library/Logs/HybridOps/core-install.log' \
  "${HYOPS_REPO_ROOT}/pkg/macos/resources/conclusion.html"
grep -Fq 'https://docs.hybridops.tech/' \
  "${HYOPS_REPO_ROOT}/pkg/macos/resources/conclusion.html"
grep -Fq 'https://github.com/hybridops-tech/hybridops-core' \
  "${HYOPS_REPO_ROOT}/pkg/macos/resources/conclusion.html"
grep -Fq 'https://github.com/hybridops-tech/hybridops-core/discussions' \
  "${HYOPS_REPO_ROOT}/pkg/macos/resources/conclusion.html"
grep -Fq 'https://github.com/hybridops-tech/hybridops-core/blob/main/CONTRIBUTING.md' \
  "${HYOPS_REPO_ROOT}/pkg/macos/resources/conclusion.html"
grep -Fq 'https://github.com/sponsors/hybridops-tech' \
  "${HYOPS_REPO_ROOT}/pkg/macos/resources/conclusion.html"
grep -Fq 'Sponsor the project</a>' \
  "${HYOPS_REPO_ROOT}/pkg/macos/resources/conclusion.html"
if grep -RqE '—|–' "${HYOPS_REPO_ROOT}/pkg/macos/resources"; then
  echo "ERR: macOS Installer resources use decorative dash characters" >&2
  exit 1
fi
if grep -Rq '<code>' "${HYOPS_REPO_ROOT}/pkg/macos/resources"; then
  echo "ERR: macOS Installer resources use inconsistent code typography" >&2
  exit 1
fi
python3 - "${HYOPS_REPO_ROOT}/pkg/macos/postinstall" <<'PY'
from pathlib import Path
import sys

script = Path(sys.argv[1]).read_text(encoding="utf-8")
created = script.index('work_dir=$(/usr/bin/mktemp -d')
traversable = script.index('/bin/chmod 0755 "${work_dir}"')
user_install = script.index('/usr/bin/sudo -H -u "${console_user}"')
assert created < traversable < user_install
PY
if grep -Eq '(-mindepth|-maxdepth)' "${HYOPS_REPO_ROOT}/pkg/macos/postinstall"; then
  echo "ERR: macOS postinstall uses GNU find options" >&2
  exit 1
fi
test -s "${HYOPS_REPO_ROOT}/pkg/macos/resources/license.html"
grep -Fq 'Runtime environments, logs and vault data were retained.' \
  "${HYOPS_REPO_ROOT}/pkg/macos/uninstall-macos.sh"
grep -Fq 'tech.hybridops.core' "${HYOPS_REPO_ROOT}/pkg/build_macos_pkg.sh"

MACOS_PKG_TEST_DIR="${WORK_DIR}/macos-pkg"
MACOS_PKG_FAKE_BIN="${MACOS_PKG_TEST_DIR}/bin"
MACOS_PKG_ARCHIVE="${MACOS_PKG_TEST_DIR}/hybridops-core-test.tar.gz"
MACOS_PKG_OUTPUT="${MACOS_PKG_TEST_DIR}/hybridops-core-test.pkg"
mkdir -p "${MACOS_PKG_FAKE_BIN}"
printf 'package fixture\n' >"${MACOS_PKG_ARCHIVE}"
cat >"${MACOS_PKG_FAKE_BIN}/uname" <<'EOF'
#!/usr/bin/env bash
echo Darwin
EOF
cat >"${MACOS_PKG_FAKE_BIN}/pkgbuild" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
root=""
scripts=""
output="${!#}"
while [[ "$#" -gt 1 ]]; do
  case "$1" in
    --root) root="$2"; shift 2 ;;
    --scripts) scripts="$2"; shift 2 ;;
    *) shift ;;
  esac
done
test -x "${root}/usr/local/share/hybridops-core/uninstall-macos.sh"
test -x "${scripts}/postinstall"
test -s "${scripts}/release.tar.gz"
test -s "${scripts}/release.tar.gz.sha256"
: >"${output}"
EOF
cat >"${MACOS_PKG_FAKE_BIN}/productbuild" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
if [[ " $* " == *" --synthesize "* ]]; then
  cat >"${!#}" <<'XML'
<?xml version="1.0" encoding="utf-8"?>
<installer-gui-script minSpecVersion="1"><options customize="never"/></installer-gui-script>
XML
  exit 0
fi
: >"${!#}"
EOF
cat >"${MACOS_PKG_FAKE_BIN}/pkgutil" <<'EOF'
#!/usr/bin/env bash
exit 1
EOF
chmod 0755 "${MACOS_PKG_FAKE_BIN}"/*
PATH="${MACOS_PKG_FAKE_BIN}:${PATH}" \
  bash "${HYOPS_REPO_ROOT}/pkg/build_macos_pkg.sh" \
    --archive "${MACOS_PKG_ARCHIVE}" \
    --version 0.1.0 \
    --output "${MACOS_PKG_OUTPUT}" >/dev/null
test -f "${MACOS_PKG_OUTPUT}"

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
