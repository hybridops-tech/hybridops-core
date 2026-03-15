#!/usr/bin/env bash
# purpose: Shared helpers for HybridOps.Core release bundle tooling.
# adr: ADR-0622
# maintainer: HybridOps.Studio

set -euo pipefail

hyops_release_require_cmd() {
  if ! command -v "$1" >/dev/null 2>&1; then
    echo "ERR: required command not found: $1" >&2
    exit 2
  fi
}

hyops_release_fs_free_bytes() {
  local path="$1"
  df -Pk "${path}" | awk 'NR == 2 { print $4 * 1024 }'
}

hyops_release_assert_free_space() {
  local path="$1"
  local required_bytes="$2"
  local hint="$3"
  local free_bytes

  free_bytes="$(hyops_release_fs_free_bytes "${path}")"
  if [[ -z "${free_bytes}" ]]; then
    echo "ERR: failed to determine free space for ${path}" >&2
    exit 2
  fi

  if (( free_bytes < required_bytes )); then
    echo "ERR: insufficient free space on filesystem for ${path}" >&2
    echo "detail: need at least ${required_bytes} bytes, have ${free_bytes} bytes" >&2
    if [[ -n "${hint}" ]]; then
      echo "hint: ${hint}" >&2
    fi
    exit 3
  fi
}

hyops_release_pkg_dir() {
  cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd
}

hyops_release_repo_root() {
  cd -- "$(hyops_release_pkg_dir)/.." && pwd
}

hyops_release_manifest_items() {
  local section="$1"
  local manifest
  manifest="$(hyops_release_repo_root)/pkg/manifest.yml"

  awk -v target="${section}" '
    $0 ~ ("^" target ":[[:space:]]*$") { in_target = 1; next }
    /^[a-z_]+:[[:space:]]*$/ { in_target = 0 }
    in_target && /^[[:space:]]*-[[:space:]]+/ {
      line = $0
      sub(/^[[:space:]]*-[[:space:]]+/, "", line)
      print line
    }
  ' "${manifest}"
}

hyops_release_prune_globs() {
  local prune_file
  prune_file="$(hyops_release_repo_root)/pkg/prune.yml"

  awk '
    /^exclude_globs:[[:space:]]*$/ { in_target = 1; next }
    /^[a-z_]+:[[:space:]]*$/ { in_target = 0 }
    in_target && /^[[:space:]]*-[[:space:]]+/ {
      line = $0
      sub(/^[[:space:]]*-[[:space:]]+/, "", line)
      print line
    }
  ' "${prune_file}"
}

hyops_release_default_label() {
  local repo_root
  repo_root="$(hyops_release_repo_root)"

  if git -C "${repo_root}" rev-parse --is-inside-work-tree >/dev/null 2>&1; then
    local label
    label="$(git -C "${repo_root}" rev-parse --short HEAD)"
    if [[ -n "$(git -C "${repo_root}" status --short --untracked-files=normal 2>/dev/null)" ]]; then
      label="${label}-dirty"
    fi
    printf '%s\n' "${label}"
    return 0
  fi

  date -u +%Y%m%dT%H%M%SZ
}

hyops_release_sanitize_label() {
  printf '%s' "$1" \
    | tr '/ ' '--' \
    | tr -cd '[:alnum:]._-'
}

hyops_release_resolve_include_path() {
  local relpath="$1"

  if [[ -e "$(hyops_release_repo_root)/${relpath}" ]]; then
    printf '%s\n' "${relpath}"
    return 0
  fi

  case "${relpath}" in
    README)
      [[ -e "$(hyops_release_repo_root)/README.md" ]] && printf '%s\n' "README.md" && return 0
      ;;
    LICENSE)
      [[ -e "$(hyops_release_repo_root)/LICENSE.txt" ]] && printf '%s\n' "LICENSE.txt" && return 0
      ;;
    CHANGELOG)
      [[ -e "$(hyops_release_repo_root)/CHANGELOG.md" ]] && printf '%s\n' "CHANGELOG.md" && return 0
      ;;
  esac

  return 1
}
