#!/usr/bin/env bash
# purpose: Build a HybridOps.Core release bundle from the current source tree.
# adr: ADR-0622
# maintainer: HybridOps.Studio

set -euo pipefail

_hyops_release_pkg_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"

# shellcheck source=/dev/null
source "${_hyops_release_pkg_dir}/lib/common.sh"

hyops_release_require_cmd python3
hyops_release_require_cmd tar
hyops_release_require_cmd sha256sum
hyops_release_require_cmd find
hyops_release_require_cmd mktemp
hyops_release_require_cmd cp

RELEASE_LABEL="${HYOPS_RELEASE_LABEL:-${VERSION:-}}"
if [[ -z "${RELEASE_LABEL}" ]]; then
  RELEASE_LABEL="$(hyops_release_default_label)"
fi
RELEASE_LABEL="$(hyops_release_sanitize_label "${RELEASE_LABEL}")"

REPO_ROOT="$(hyops_release_repo_root)"
OUT_DIR="${OUT_DIR:-${REPO_ROOT}/dist/releases}"
PACKAGE_ROOT="hybridops-core-${RELEASE_LABEL}"
TARBALL_PATH="${OUT_DIR}/${PACKAGE_ROOT}.tar.gz"
SHA256_PATH="${TARBALL_PATH}.sha256"
BUILD_WHEELHOUSE="${HYOPS_RELEASE_BUILD_WHEELHOUSE:-true}"

WORK_DIR="$(mktemp -d)"
STAGE_ROOT="${WORK_DIR}/${PACKAGE_ROOT}"

cleanup() {
  rm -rf "${WORK_DIR}"
}
trap cleanup EXIT

mkdir -p "${OUT_DIR}" "${STAGE_ROOT}"

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
    path_bytes="$(du -sb "${REPO_ROOT}/${source_relpath}" | awk '{print $1}')"
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
  local pattern=""
  shopt -s dotglob globstar nullglob
  while IFS= read -r pattern; do
    [[ -n "${pattern}" ]] || continue
    for match in "${STAGE_ROOT}"/${pattern}; do
      rm -rf "${match}"
    done
  done < <(hyops_release_prune_globs)
  shopt -u dotglob globstar nullglob
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
HYOPS_RELEASE_BUILD_UTC=${build_utc}
HYOPS_RELEASE_SOURCE_COMMIT=${commit_ref}
HYOPS_RELEASE_SOURCE_BRANCH=${branch_ref}
HYOPS_RELEASE_BUILD_WHEELHOUSE=${BUILD_WHEELHOUSE}
EOF
}

write_release_checksums() {
  local checksum_file="${STAGE_ROOT}/pkg/release-files.sha256"
  (
    cd "${STAGE_ROOT}"
    find . -type f ! -path './pkg/release-files.sha256' -print0 \
      | sort -z \
      | xargs -0 sha256sum \
      | sed 's| \./| |'
  ) >"${checksum_file}"
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
build_wheelhouse
prune_stage
write_release_metadata
write_release_checksums

tar -C "${WORK_DIR}" -czf "${TARBALL_PATH}" "${PACKAGE_ROOT}"
(
  cd "${OUT_DIR}"
  sha256sum "$(basename "${TARBALL_PATH}")" >"$(basename "${SHA256_PATH}")"
)

echo "Built bundle:"
echo "  ${TARBALL_PATH}"
echo "Checksum:"
echo "  ${SHA256_PATH}"
