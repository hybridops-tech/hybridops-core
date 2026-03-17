#!/usr/bin/env bash
# purpose: Run HybridOps.Core Terraform quality checks against shipped stacks.
# adr: ADR-0622
# maintainer: HybridOps.Tech

set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=/dev/null
source "${SCRIPT_DIR}/lib/common.sh"

hyops_ci::require_cmd terraform
hyops_ci::require_cmd tflint

tmpdir="$(mktemp -d)"
trap 'rm -rf "${tmpdir}"' EXIT

cache_root="$(hyops_ci::cache_root)"
export TF_PLUGIN_CACHE_DIR="${HYOPS_CI_TERRAFORM_PLUGIN_CACHE_DIR:-${cache_root}/terraform/plugin-cache}"
export TF_REGISTRY_CLIENT_TIMEOUT="${TF_REGISTRY_CLIENT_TIMEOUT:-30}"
mkdir -p "${TF_PLUGIN_CACHE_DIR}"

# First-time provider downloads for the shipped stack set are large enough to
# fail late on cramped workstations. Reuse a persistent cache and fail early
# with a clear message if the cache filesystem is too full to populate it.
if ! find "${TF_PLUGIN_CACHE_DIR}" -mindepth 1 -print -quit | grep -q .; then
  free_bytes="$(hyops_ci::fs_free_bytes "${TF_PLUGIN_CACHE_DIR}")"
  if (( free_bytes < 2147483648 )); then
    echo "ERR: Terraform quality gate requires at least 2 GiB free on $(dirname "${TF_PLUGIN_CACHE_DIR}") for initial provider cache population." >&2
    echo "hint: clear disposable caches or set HYOPS_CI_TERRAFORM_PLUGIN_CACHE_DIR to a larger filesystem." >&2
    exit 2
  fi
fi

terraform fmt -check -recursive "${HYOPS_REPO_ROOT}/packs/iac/terragrunt"

while IFS= read -r stack_dir; do
  hyops_ci::retry 3 \
    terraform -chdir="${stack_dir}" init -backend=false -input=false -no-color >/dev/null
  terraform -chdir="${stack_dir}" validate -no-color
  tflint --chdir "${stack_dir}" --format compact
  rm -rf "${stack_dir}/.terraform" "${stack_dir}/.terraform.lock.hcl"
done < <(hyops_ci::all_terraform_stacks)
