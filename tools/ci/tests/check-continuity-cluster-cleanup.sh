#!/usr/bin/env bash
set -euo pipefail

harness="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)/check-continuity-api.sh"
tmp="$(mktemp -d)"
trap 'rm -rf "${tmp}"' EXIT
export trace="${tmp}/trace" scenario
export suffix_file="${tmp}/cluster-suffix"

python3() { command python3 "$@" | tee "${suffix_file}"; }
docker() { return 99; }
kind() {
  local test_cluster=""
  if [[ -s "${suffix_file}" ]]; then test_cluster="hyops-api-$(<"${suffix_file}")"; fi
  case "$1 ${2:-}" in
    "version ") printf 'kind v%s test\n' "${KIND_VERSION}" ;;
    "get clusters")
      echo inventory >>"${trace}"
      case "${scenario}" in
        inventory-error) return 2 ;;
        existing) echo "${test_cluster}" ;;
        partial) if grep -Fxq create "${trace}"; then echo "${test_cluster}"; fi ;;
        inventory-lost) if grep -Fxq create "${trace}"; then return 2; fi ;;
      esac ;;
    "create cluster")
      [[ "$4" == "${test_cluster}" && ${#4} -le 49 ]] || return 90
      echo create >>"${trace}"
      case "${scenario}" in partial|rolled-back|inventory-lost) return 2 ;; esac ;;
    "get kubeconfig")
      echo identity >>"${trace}"
      case "${scenario}" in
        replaced) echo other-ca ;;
        identity-lost) return 2 ;;
        *) echo initial-ca ;;
      esac ;;
    "delete cluster")
      [[ "$4" == "${test_cluster}" ]] || return 90
      echo delete >>"${trace}" ;;
    *) return 99 ;;
  esac
}
kubectl() {
  [[ "$1 $2" == 'config view' ]] || return 19
  if [[ "$3" == --kubeconfig=/dev/stdin ]]; then cat; else echo initial-ca; fi
}
export -f python3 docker kind kubectl

check_case() {
  scenario="$1"
  : >"${trace}"
  # A successful create stops at the first kubectl apply, exercising the exit trap.
  if bash "${harness}" >"${tmp}/output" 2>&1; then
    echo "ERR: ${scenario}: expected nonzero exit" >&2
    return 1
  fi
  local actual
  actual="$(paste -sd ' ' "${trace}")"
  if [[ "${actual}" != "$2" ]]; then
    cat "${tmp}/output" >&2
    echo "ERR: ${scenario}: expected '$2', got '${actual}'" >&2
    return 1
  fi
  if [[ -n "${3:-}" ]]; then grep -Fq -- "$3" "${tmp}/output"; fi
}

check_case existing 'inventory' 'already exists'
check_case inventory-error 'inventory'
check_case rolled-back 'inventory create inventory'
check_case partial 'inventory create inventory' 'not deleting'
check_case inventory-lost 'inventory create inventory' 'not deleting'
check_case owned 'inventory create identity delete'
check_case replaced 'inventory create identity' 'not deleting'
check_case identity-lost 'inventory create identity' 'not deleting'
