#!/usr/bin/env bash
# purpose: Shared low-level install helpers.
# Architecture Decision: ADR-N/A (bootstrap installer)
# maintainer: HybridOps.Studio

hyops_install_need_cmd() {
  command -v "$1" >/dev/null 2>&1 || {
    echo "ERR: missing command: $1" >&2
    exit 2
  }
}

hyops_install_set_blueprint_payload_read_only() {
  local root="$1"
  local bp_root="${root}/blueprints"
  [[ -d "${bp_root}" ]] || return 0

  find "${bp_root}" -type d -exec chmod 0755 {} +
  find "${bp_root}" -type f \( -name '*.yml' -o -name '*.yaml' \) -exec chmod 0444 {} +
}

hyops_install_abs_path() {
  local raw_path="$1"
  python3 - <<PY
import os
print(os.path.abspath(os.path.expanduser(${raw_path@Q})))
PY
}

hyops_install_remove_or_fail_dir() {
  local target_dir="$1"
  local label="$2"

  if [[ -d "${target_dir}" ]]; then
    if [[ "${FORCE}" == "true" ]]; then
      echo "[install] removing ${target_dir}"
      rm -rf "${target_dir}"
    else
      echo "ERR: ${label} already exists: ${target_dir} (use --force)" >&2
      exit 2
    fi
  fi
}
