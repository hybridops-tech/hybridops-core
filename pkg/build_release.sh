#!/usr/bin/env bash
# purpose: Build a HybridOps.Core release bundle from the current source tree.
# adr: ADR-0622
# maintainer: HybridOps.Tech

set -euo pipefail

_hyops_release_pkg_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"

# shellcheck source=/dev/null
source "${_hyops_release_pkg_dir}/lib/common.sh"

hyops_release_require_cmd python3
hyops_release_require_cmd tar
hyops_release_require_cmd find
hyops_release_require_cmd mktemp
hyops_release_require_cmd cp

RELEASE_LABEL="${HYOPS_RELEASE_LABEL:-${VERSION:-}}"
if [[ -z "${RELEASE_LABEL}" ]]; then
  RELEASE_LABEL="$(hyops_release_default_label)"
fi
RELEASE_LABEL="$(hyops_release_sanitize_label "${RELEASE_LABEL}")"
RELEASE_VERSION="${HYOPS_RELEASE_VERSION:-}"
if [[ -z "${RELEASE_VERSION}" && "${RELEASE_LABEL}" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
  RELEASE_VERSION="${RELEASE_LABEL}"
fi
if [[ -n "${RELEASE_VERSION}" && ! "${RELEASE_VERSION}" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
  echo "ERR: HYOPS_RELEASE_VERSION must use X.Y.Z numeric form" >&2
  exit 2
fi

REPO_ROOT="$(hyops_release_repo_root)"
OUT_DIR="${OUT_DIR:-${REPO_ROOT}/dist/releases}"
PACKAGE_ROOT="hybridops-core-${RELEASE_LABEL}"
TARBALL_PATH="${OUT_DIR}/${PACKAGE_ROOT}.tar.gz"
SHA256_PATH="${TARBALL_PATH}.sha256"
WINDOWS_INSTALLER_SOURCE="${REPO_ROOT}/tools/install/windows/install-windows.cmd"
WINDOWS_HELPER_PATH="${REPO_ROOT}/tools/install/windows/install-windows-wsl.sh"
WINDOWS_BUNDLE_PATH="${OUT_DIR}/${PACKAGE_ROOT}-windows.zip"
WINDOWS_BUNDLE_SHA256_PATH="${WINDOWS_BUNDLE_PATH}.sha256"
BUILD_WHEELHOUSE="${HYOPS_RELEASE_BUILD_WHEELHOUSE:-true}"

WORK_DIR="$(mktemp -d)"
STAGE_ROOT="${WORK_DIR}/${PACKAGE_ROOT}"

cleanup() {
  rm -rf "${WORK_DIR}"
}
trap cleanup EXIT

mkdir -p "${OUT_DIR}" "${STAGE_ROOT}"
rm -f "${OUT_DIR}/install-windows.ps1"

estimate_manifest_bytes() {
  local relpath=""
  local source_relpath=""
  local total_bytes=0
  local path_bytes=0

  while IFS= read -r relpath; do
    [[ -n "${relpath}" ]] || continue
    if ! source_relpath="$(hyops_release_resolve_include_path "${relpath}")"; then
      continue
    fi
    path_bytes="$(du -sk "${REPO_ROOT}/${source_relpath}" | awk '{print $1 * 1024}')"
    total_bytes=$(( total_bytes + path_bytes ))
  done < <(hyops_release_manifest_items include)

  printf '%s\n' "${total_bytes}"
}

warn_if_temp_space_is_low() {
  local approx_source_bytes
  local approx_required_bytes
  local free_bytes

  approx_source_bytes="$(estimate_manifest_bytes)"
  approx_required_bytes=$(( approx_source_bytes + 67108864 ))
  free_bytes="$(hyops_release_fs_free_bytes "${WORK_DIR}")"

  if (( free_bytes < approx_required_bytes )); then
    echo "WARN: low free space for release build temp area" >&2
    echo "detail: approximately ${approx_required_bytes} bytes recommended, ${free_bytes} bytes available on ${WORK_DIR}" >&2
    echo "hint: if this build fails mid-run, re-run with TMPDIR on a larger filesystem" >&2
  fi
}

copy_manifest_paths() {
  local relpath=""
  local source_relpath=""
  while IFS= read -r relpath; do
    [[ -n "${relpath}" ]] || continue
    if ! source_relpath="$(hyops_release_resolve_include_path "${relpath}")"; then
      echo "WARN: manifest path missing, skipping: ${relpath}" >&2
      continue
    fi
    mkdir -p "$(dirname "${STAGE_ROOT}/${relpath%/}")"
    cp -a "${REPO_ROOT}/${source_relpath}" "${STAGE_ROOT}/${relpath}"
  done < <(hyops_release_manifest_items include)
}

prune_stage() {
  local patterns_file="${WORK_DIR}/prune-patterns.txt"
  hyops_release_prune_globs >"${patterns_file}"
  python3 - "${STAGE_ROOT}" "${patterns_file}" <<'PY'
from pathlib import Path
import shutil
import sys

root = Path(sys.argv[1])
patterns = [line.strip() for line in Path(sys.argv[2]).read_text().splitlines() if line.strip()]
matches = set()
for pattern in patterns:
    matches.update(root.glob(pattern))
for path in sorted(matches, key=lambda item: len(item.parts), reverse=True):
    if path.is_symlink() or path.is_file():
        path.unlink(missing_ok=True)
    elif path.is_dir():
        shutil.rmtree(path)
PY
}

write_release_version() {
  if [[ -z "${RELEASE_VERSION}" ]]; then
    RELEASE_VERSION="$(python3 - "${STAGE_ROOT}/hyops/__init__.py" <<'PY'
from pathlib import Path
import re
import sys

text = Path(sys.argv[1]).read_text(encoding="utf-8")
match = re.search(r'^__version__ = "([^"]+)"$', text, flags=re.MULTILINE)
if not match:
    raise SystemExit("release source version was not found")
print(match.group(1))
PY
)"
    return 0
  fi

  python3 - "${STAGE_ROOT}" "${RELEASE_VERSION}" <<'PY'
from pathlib import Path
import re
import sys

root = Path(sys.argv[1])
version = sys.argv[2]

init_path = root / "hyops" / "__init__.py"
init_text = init_path.read_text(encoding="utf-8")
init_text, count = re.subn(
    r'^__version__ = "[^"]+"$',
    f'__version__ = "{version}"',
    init_text,
    count=1,
    flags=re.MULTILINE,
)
if count != 1:
    raise SystemExit("unable to set runtime release version")
init_path.write_text(init_text, encoding="utf-8")

project_path = root / "pyproject.toml"
project_text = project_path.read_text(encoding="utf-8")
project_text, count = re.subn(
    r'^version = "[^"]+"$',
    f'version = "{version}"',
    project_text,
    count=1,
    flags=re.MULTILINE,
)
if count != 1:
    raise SystemExit("unable to set Python package release version")
project_path.write_text(project_text, encoding="utf-8")
PY
}

write_release_metadata() {
  local commit_ref="unknown"
  local branch_ref="unknown"
  local build_utc
  build_utc="$(date -u +%Y-%m-%dT%H:%M:%SZ)"

  if git -C "${REPO_ROOT}" rev-parse --is-inside-work-tree >/dev/null 2>&1; then
    commit_ref="$(git -C "${REPO_ROOT}" rev-parse HEAD)"
    branch_ref="$(git -C "${REPO_ROOT}" rev-parse --abbrev-ref HEAD)"
  fi

  cat >"${STAGE_ROOT}/pkg/release-metadata.env" <<EOF
HYOPS_RELEASE_LABEL=${RELEASE_LABEL}
HYOPS_RELEASE_VERSION=${RELEASE_VERSION}
HYOPS_RELEASE_BUILD_UTC=${build_utc}
HYOPS_RELEASE_SOURCE_COMMIT=${commit_ref}
HYOPS_RELEASE_SOURCE_BRANCH=${branch_ref}
HYOPS_RELEASE_BUILD_WHEELHOUSE=${BUILD_WHEELHOUSE}
EOF
}

write_release_checksums() {
  local checksum_file="${STAGE_ROOT}/pkg/release-files.sha256"
  python3 - "${STAGE_ROOT}" "${checksum_file}" <<'PY'
from hashlib import sha256
from pathlib import Path
import sys

root = Path(sys.argv[1])
checksum_file = Path(sys.argv[2])
lines = []
for path in sorted(item for item in root.rglob("*") if item.is_file()):
    if path == checksum_file:
        continue
    digest = sha256(path.read_bytes()).hexdigest()
    lines.append(f"{digest}  {path.relative_to(root)}")
checksum_file.write_text("\n".join(lines) + "\n", encoding="utf-8")
PY
}

build_wheelhouse() {
  if [[ "${BUILD_WHEELHOUSE}" != "true" ]]; then
    return 0
  fi

  local wheel_venv="${WORK_DIR}/wheel-venv"
  mkdir -p "${STAGE_ROOT}/wheels"
  python3 -m venv "${wheel_venv}"
  "${wheel_venv}/bin/python" -m pip install --upgrade pip >/dev/null
  "${wheel_venv}/bin/python" -m pip wheel --wheel-dir "${STAGE_ROOT}/wheels" "${STAGE_ROOT}" >/dev/null
}

warn_if_temp_space_is_low
copy_manifest_paths
prune_stage
chmod 0755 "${STAGE_ROOT}/install.sh" 2>/dev/null || true
write_release_version
build_wheelhouse
prune_stage
write_release_metadata
write_release_checksums

tar -C "${WORK_DIR}" -czf "${TARBALL_PATH}" "${PACKAGE_ROOT}"
(
  cd "${OUT_DIR}"
  python3 - "$(basename "${TARBALL_PATH}")" "$(basename "${SHA256_PATH}")" <<'PY'
from hashlib import sha256
from pathlib import Path
import sys

archive = Path(sys.argv[1])
target = Path(sys.argv[2])
target.write_text(f"{sha256(archive.read_bytes()).hexdigest()}  {archive.name}\n", encoding="utf-8")
PY
)
WINDOWS_STAGE="${WORK_DIR}/${PACKAGE_ROOT}-windows"
WINDOWS_PAYLOAD_STAGE="${WINDOWS_STAGE}/payload"
mkdir -p "${WINDOWS_PAYLOAD_STAGE}"
cp "${WINDOWS_INSTALLER_SOURCE}" "${WINDOWS_STAGE}/Install HybridOps.cmd"
cp "${TARBALL_PATH}" "${WINDOWS_PAYLOAD_STAGE}/hybridops-core.tar.gz"
cp "${WINDOWS_HELPER_PATH}" "${WINDOWS_PAYLOAD_STAGE}/install-wsl.sh"
cp "${REPO_ROOT}/assets/windows/hybridops.ico" "${WINDOWS_PAYLOAD_STAGE}/hybridops.ico"
(
  cd "${WINDOWS_PAYLOAD_STAGE}"
  sha256sum hybridops-core.tar.gz >hybridops-core.tar.gz.sha256
)
python3 - "${REPO_ROOT}/LICENSE" "${WINDOWS_STAGE}/LICENSE.txt" <<'PY'
from pathlib import Path
import sys

source = Path(sys.argv[1]).read_text(encoding="utf-8")
lines = []
for line in source.splitlines():
    if line.strip() == "---":
        continue
    if line.startswith("# "):
        line = line[2:]
    line = line.replace("**", "").replace("`", "")
    if line.startswith("- Attribution — "):
        line = "Attribution: " + line.removeprefix("- Attribution — ")
    elif line.startswith("  "):
        line = line[2:]
    if not line and lines and not lines[-1]:
        continue
    lines.append(line)

while lines and not lines[-1]:
    lines.pop()
Path(sys.argv[2]).write_text("\n".join(lines) + "\n", encoding="utf-8")
PY
cat >"${WINDOWS_STAGE}/README.txt" <<EOF
HybridOps.Core for Windows 11 (WSL2)

1. Extract every file from this ZIP archive.
2. Run Install HybridOps.cmd.

After a successful installation, use the optional HybridOps.Core desktop
shortcut or open Ubuntu 24.04 from the Windows Start menu.

The first Ubuntu launch may ask you to create a Linux username and password.
Complete that prompt. Control returns to the installer automatically.

If Windows features require a reboot, the bootstrap asks before scheduling it.
The default answer is No.

For replacement of an existing installation, run Install HybridOps.cmd --force.

The bootstrap verifies the included release archive, prepares Ubuntu 24.04 on
WSL2, and starts the HybridOps.Core installer.

The initial installation provides the HybridOps CLI. Install prerequisites for
one target afterward:
  hyops setup gcp
  hyops setup azure
  hyops setup proxmox
EOF
python3 - "${WINDOWS_STAGE}" "${WINDOWS_BUNDLE_PATH}" <<'PY'
from pathlib import Path
import sys
import zipfile

source = Path(sys.argv[1])
target = Path(sys.argv[2])
with zipfile.ZipFile(target, "w", compression=zipfile.ZIP_DEFLATED) as archive:
    for path in sorted(item for item in source.rglob("*") if item.is_file()):
        archive.write(path, arcname=path.relative_to(source))
PY
python3 - "${WINDOWS_BUNDLE_PATH}" <<'PY'
from pathlib import Path
import sys
import zipfile

expected = {
    "Install HybridOps.cmd",
    "LICENSE.txt",
    "README.txt",
    "payload/hybridops-core.tar.gz",
    "payload/hybridops-core.tar.gz.sha256",
    "payload/hybridops.ico",
    "payload/install-wsl.sh",
}
with zipfile.ZipFile(Path(sys.argv[1])) as archive:
    actual = set(archive.namelist())
if actual != expected:
    missing = sorted(expected - actual)
    unexpected = sorted(actual - expected)
    raise SystemExit(f"invalid Windows bundle layout: missing={missing}, unexpected={unexpected}")
PY
(
  cd "${OUT_DIR}"
  sha256sum "$(basename "${WINDOWS_BUNDLE_PATH}")" >"$(basename "${WINDOWS_BUNDLE_SHA256_PATH}")"
)

echo "Built bundle:"
echo "  ${TARBALL_PATH}"
echo "Checksum:"
echo "  ${SHA256_PATH}"
echo "Windows bundle:"
echo "  ${WINDOWS_BUNDLE_PATH}"
echo "Windows bundle checksum:"
echo "  ${WINDOWS_BUNDLE_SHA256_PATH}"
