#!/usr/bin/env bash
# purpose: Shared helpers for HybridOps.Core CI quality scripts.
# adr: ADR-0622
# maintainer: HybridOps.Tech

[[ -n "${HYOPS_CI_COMMON_SH:-}" ]] && return 0
HYOPS_CI_COMMON_SH=1

HYOPS_CI_LIB_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
HYOPS_REPO_ROOT="$(cd -- "${HYOPS_CI_LIB_DIR}/../../.." && pwd)"

# shellcheck source=/dev/null
source "${HYOPS_REPO_ROOT}/tools/setup/requirements/toolchain.lock"

hyops_ci::require_cmd() {
  command -v "$1" >/dev/null 2>&1 || {
    echo "ERR: missing command: $1" >&2
    exit 2
  }
}

hyops_ci::fs_free_bytes() {
  local path="$1"
  df -B1 --output=avail "${path}" | tail -n1 | tr -d '[:space:]'
}

hyops_ci::cache_root() {
  if [[ -n "${HYOPS_CI_CACHE_ROOT:-}" ]]; then
    printf '%s\n' "${HYOPS_CI_CACHE_ROOT}"
    return 0
  fi
  printf '%s\n' "${XDG_CACHE_HOME:-${HOME}/.cache}/hyops/ci"
}

hyops_ci::retry() {
  local attempts="$1"
  shift

  local delay_s="${HYOPS_CI_RETRY_DELAY_S:-3}"
  local try=1

  until "$@"; do
    if (( try >= attempts )); then
      return 1
    fi
    sleep "${delay_s}"
    try=$(( try + 1 ))
  done
}

hyops_ci::write_filtered_requirements() {
  local source_file="$1"
  local target_file="$2"

  python3 - "${source_file}" "${target_file}" <<'PY'
from pathlib import Path
import sys

import yaml

source_path = Path(sys.argv[1]).resolve()
target_path = Path(sys.argv[2]).resolve()
data = yaml.safe_load(source_path.read_text(encoding="utf-8")) or {}

collections = [
    item
    for item in (data.get("collections") or [])
    if not str(item.get("name", "")).startswith("hybridops.")
]

payload = {"collections": collections}
roles = data.get("roles") or []
if roles:
    payload["roles"] = roles

target_path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")
PY
}

hyops_ci::requirements_has_roles() {
  local requirements_file="$1"

  python3 - "${requirements_file}" <<'PY'
from pathlib import Path
import sys

import yaml

data = yaml.safe_load(Path(sys.argv[1]).read_text(encoding="utf-8")) or {}
raise SystemExit(0 if data.get("roles") else 1)
PY
}

hyops_ci::prepare_ansible_dependencies() {
  local runtime_root="$1"
  local filtered=""

  mkdir -p "${runtime_root}/collections" "${runtime_root}/roles"
  export ANSIBLE_COLLECTIONS_PATH="${runtime_root}/collections"
  export ANSIBLE_ROLES_PATH="${runtime_root}/roles"

  while IFS= read -r requirements_file; do
    filtered="${runtime_root}/$(basename "${requirements_file}")"
    hyops_ci::write_filtered_requirements "${requirements_file}" "${filtered}"

    ANSIBLE_GALAXY_DISABLE_GPG_VERIFY=1 \
      ansible-galaxy collection install \
      -r "${filtered}" \
      -p "${runtime_root}/collections" \
      >/dev/null

    if hyops_ci::requirements_has_roles "${filtered}"; then
      ANSIBLE_GALAXY_DISABLE_GPG_VERIFY=1 \
        ansible-galaxy role install \
        -r "${filtered}" \
        -p "${runtime_root}/roles" \
        >/dev/null
    fi
  done < <(find "${HYOPS_REPO_ROOT}/tools/setup/requirements" -maxdepth 1 -name 'ansible*.galaxy.yml' | sort)
}

hyops_ci::export_ansible_runtime() {
  local runtime_root="$1"

  export ANSIBLE_COLLECTIONS_PATH="${HYOPS_REPO_ROOT}/hyops/drivers/config/ansible/collections:${runtime_root}/collections"
  export ANSIBLE_ROLES_PATH="${runtime_root}/roles"
  export ANSIBLE_NOCOLOR=1
}

hyops_ci::all_ansible_playbooks() {
  find "${HYOPS_REPO_ROOT}/packs/config/ansible" -path '*/stack/playbook*.yml' -type f | sort
}

hyops_ci::all_ansible_role_roots() {
  find "${HYOPS_REPO_ROOT}/hyops/drivers/config/ansible/collections/ansible_collections/hybridops" -mindepth 2 -maxdepth 2 -type d -name roles | sort
}

hyops_ci::all_terraform_stacks() {
  find "${HYOPS_REPO_ROOT}/packs/iac/terragrunt" -path '*/stack/terraform' -type d | sort
}
