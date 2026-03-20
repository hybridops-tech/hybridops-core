#!/usr/bin/env bash
# purpose: Run HybridOps.Core Ansible lint checks against core-owned playbooks and pack wrappers.
# adr: ADR-0622
# maintainer: HybridOps.Tech

set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=/dev/null
source "${SCRIPT_DIR}/lib/common.sh"

hyops_ci::require_cmd python3
hyops_ci::require_cmd ansible-galaxy
hyops_ci::require_cmd ansible-lint

tmpdir="$(mktemp -d)"
trap 'rm -rf "${tmpdir}"' EXIT
project_dir="${tmpdir}/project"
mkdir -p "${project_dir}"

hyops_ci::prepare_ansible_dependencies "${tmpdir}"
hyops_ci::export_ansible_runtime "${tmpdir}"

cd "${HYOPS_REPO_ROOT}"

mapfile -t ansible_targets < <(hyops_ci::all_ansible_playbooks | sed "s#^${HYOPS_REPO_ROOT}/##")
config_file="${HYOPS_REPO_ROOT}/tools/ci/ansible-lint.yml"
ansible-lint \
  -c "${config_file}" \
  --project-dir "${project_dir}" \
  --offline \
  --exclude 'blueprints/' \
  --exclude 'modules/' \
  --exclude '*/molecule/' \
  --exclude '*/tests/' \
  "${ansible_targets[@]}"
