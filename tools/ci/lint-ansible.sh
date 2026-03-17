#!/usr/bin/env bash
# purpose: Run HybridOps.Core advisory Ansible lint checks against shipped roles.
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

hyops_ci::prepare_ansible_dependencies "${tmpdir}"
hyops_ci::export_ansible_runtime "${tmpdir}"

mapfile -t role_roots < <(hyops_ci::all_ansible_role_roots)
ansible-lint \
  --offline \
  --exclude '*/molecule/' \
  --exclude '*/tests/' \
  "${role_roots[@]}"
