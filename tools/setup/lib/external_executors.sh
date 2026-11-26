#!/usr/bin/env bash
# purpose: Verify operator-supplied executors required by HybridOps.Core.
# architecture decision: ADR-N/A
# maintainer: HybridOps.Tech

hyops_external__command_path() {
  command -v "$1" 2>/dev/null || true
}

hyops_external__run_version() {
  if command -v timeout >/dev/null 2>&1; then
    timeout --foreground 20s "$@" 2>/dev/null || true
    return
  fi
  "$@" 2>/dev/null || true
}

hyops_external__version_supported() {
  local actual="${1#v}"
  local minimum="${2#v}"
  python3 - "${actual}" "${minimum}" <<'PY'
import re
import sys


def version(value):
    match = re.match(r"^(\d+(?:\.\d+)*)", value)
    if not match:
        raise ValueError(value)
    return tuple(int(part) for part in match.group(1).split("."))


try:
    actual = version(sys.argv[1])
    minimum = version(sys.argv[2])
except ValueError:
    raise SystemExit(1)

width = max(len(actual), len(minimum))
actual += (0,) * (width - len(actual))
minimum += (0,) * (width - len(minimum))
raise SystemExit(0 if actual[0] == minimum[0] and actual >= minimum else 1)
PY
}

hyops_external__required_range() {
  local minimum="${1#v}"
  local major="${minimum%%.*}"
  printf '>=%s,<%s.0.0' "${minimum}" "$((major + 1))"
}

hyops_external__terraform_version() {
  local command_path=""
  command_path="$(hyops_external__command_path terraform)"
  [[ -n "${command_path}" ]] || return 0
  hyops_external__run_version "${command_path}" version \
    | head -n1 \
    | sed -E 's/^Terraform v//; s/[[:space:]].*$//' || true
}

hyops_external__packer_version() {
  local command_path="" resolved_path=""
  command_path="$(hyops_external__command_path packer)"
  [[ -n "${command_path}" ]] || return 0
  resolved_path="${command_path}"
  if command -v readlink >/dev/null 2>&1; then
    resolved_path="$(readlink -f "${command_path}" 2>/dev/null || printf '%s' "${command_path}")"
  fi
  [[ "${resolved_path}" != *cracklib-packer* ]] || return 0
  hyops_external__run_version "${command_path}" version \
    | head -n1 \
    | sed -E 's/^Packer v//; s/[[:space:]].*$//' || true
}

hyops_external__ansible_core_version() {
  local command_path="" line=""
  command_path="$(hyops_external__command_path ansible)"
  [[ -n "${command_path}" ]] || return 0
  line="$(ANSIBLE_LOCAL_TEMP=/tmp/hyops-ansible-local \
    hyops_external__run_version "${command_path}" --version \
    | head -n1 \
    | tr -d '\r' || true)"
  if [[ "${line}" =~ \[core[[:space:]]+([0-9]+(\.[0-9]+)+)\] ]]; then
    printf '%s\n' "${BASH_REMATCH[1]}"
    return 0
  fi
  if [[ "${line}" =~ ^ansible(-core)?[[:space:]]+([0-9]+(\.[0-9]+)+) ]]; then
    printf '%s\n' "${BASH_REMATCH[2]}"
  fi
}

hyops_external__require_commands() {
  local label="$1"
  shift
  local command_name="" missing=()
  for command_name in "$@"; do
    if [[ -z "$(hyops_external__command_path "${command_name}")" ]]; then
      missing+=("${command_name}")
    fi
  done
  if [[ "${#missing[@]}" -gt 0 ]]; then
    echo "ERR: ${label} unavailable on PATH (missing: ${missing[*]})." >&2
    return 1
  fi
}

hyops_external__require_version() {
  local label="$1"
  local command_name="$2"
  local minimum="$3"
  local version_function="$4"
  local actual="" command_path=""
  actual="$(${version_function})"
  command_path="$(hyops_external__command_path "${command_name}")"
  if ! hyops_external__version_supported "${actual}" "${minimum}"; then
    echo "ERR: ${label} version unsupported (required=$(hyops_external__required_range "${minimum}") actual=${actual:-unknown})." >&2
    return 1
  fi
  echo "[setup] ${label} ok (v${actual} at ${command_path})"
}

hyops_setup_verify_external_executors() {
  local terraform_minimum="$1"
  local packer_minimum="$2"
  local ansible_core_minimum="$3"
  local failed=0

  if hyops_external__require_commands terraform terraform; then
    hyops_external__require_version \
      terraform terraform "${terraform_minimum}" \
      hyops_external__terraform_version || failed=1
  else
    failed=1
  fi

  if hyops_external__require_commands packer packer; then
    hyops_external__require_version \
      packer packer "${packer_minimum}" \
      hyops_external__packer_version || failed=1
  else
    failed=1
  fi

  if hyops_external__require_commands \
    ansible-core ansible ansible-playbook ansible-galaxy ansible-vault; then
    hyops_external__require_version \
      ansible-core ansible "${ansible_core_minimum}" \
      hyops_external__ansible_core_version || failed=1
  else
    failed=1
  fi

  if [[ "${failed}" -ne 0 ]]; then
    echo "ERR: required operator-supplied executors are not ready." >&2
    echo "hint: install or update Terraform, Packer and Ansible on PATH, then rerun: hyops setup base" >&2
    return 2
  fi
}
