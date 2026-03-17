#!/usr/bin/env bash
# purpose: Run HybridOps.Core Ansible syntax checks against shipped playbooks.
# adr: ADR-0622
# maintainer: HybridOps.Tech

set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=/dev/null
source "${SCRIPT_DIR}/lib/common.sh"

hyops_ci::require_cmd python3
hyops_ci::require_cmd ansible-galaxy
hyops_ci::require_cmd ansible-playbook

tmpdir="$(mktemp -d)"
trap 'rm -rf "${tmpdir}"' EXIT

hyops_ci::prepare_ansible_dependencies "${tmpdir}"
hyops_ci::export_ansible_runtime "${tmpdir}"

while IFS= read -r playbook; do
  ansible-playbook \
    -i "${HYOPS_REPO_ROOT}/tools/ci/ansible-empty.inventory.yml" \
    --syntax-check \
    "${playbook}"
done < <(hyops_ci::all_ansible_playbooks)
