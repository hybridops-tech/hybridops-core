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

export TF_PLUGIN_CACHE_DIR="${tmpdir}/plugin-cache"
mkdir -p "${TF_PLUGIN_CACHE_DIR}"

terraform fmt -check -recursive "${HYOPS_REPO_ROOT}/packs/iac/terragrunt"

while IFS= read -r stack_dir; do
  terraform -chdir="${stack_dir}" init -backend=false -input=false -no-color >/dev/null
  terraform -chdir="${stack_dir}" validate -no-color
  tflint --chdir "${stack_dir}" --format compact
  rm -rf "${stack_dir}/.terraform" "${stack_dir}/.terraform.lock.hcl"
done < <(hyops_ci::all_terraform_stacks)
