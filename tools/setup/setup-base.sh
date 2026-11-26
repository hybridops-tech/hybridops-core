#!/usr/bin/env bash
# purpose: Install base system prerequisites for HybridOps.Core (pinned toolchain).
# Architecture Decision: ADR-N/A
# maintainer: HybridOps.Tech

set -euo pipefail

if [[ "$(uname -s 2>/dev/null || true)" == "Darwin" ]]; then
  exec bash "$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)/setup-base-macos.sh" "$@"
fi

[[ "${EUID}" -eq 0 ]] || { echo "ERR: requires root (run: hyops setup base)"; exit 2; }

export PATH="/usr/local/bin:/usr/local/sbin:${PATH}"

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
RELEASE_ROOT="$(cd -- "${SCRIPT_DIR}/../.." && pwd)"

# shellcheck source=/dev/null
source "${RELEASE_ROOT}/tools/setup/lib/toolchain_lock.sh"
# shellcheck source=/dev/null
source "${RELEASE_ROOT}/tools/setup/lib/external_executors.sh"

cmd_path() { command -v "$1" 2>/dev/null || true; }

tool_cmd_path() {
  local name="$1"
  local preferred="/usr/local/bin/${name}"
  if [[ -x "${preferred}" ]]; then
    echo "${preferred}"
    return 0
  fi
  cmd_path "${name}"
}

ver_major() {
  local v="${1#v}"
  echo "${v%%.*}"
}

ver_ok_min_same_major() {
  local actual="${1#v}"
  local expected="${2#v}"
  local highest=""
  [[ -n "${actual}" && -n "${expected}" ]] || return 1
  [[ "$(ver_major "${actual}")" == "$(ver_major "${expected}")" ]] || return 1
  highest="$(printf '%s\n%s\n' "${actual}" "${expected}" | sort -V | tail -n1)"
  [[ "${highest}" == "${actual}" ]]
}

print_header() {
  local lock_path
  lock_path="$(toolchain__lock_path 2>/dev/null || echo "${RELEASE_ROOT}/tools/setup/requirements/toolchain.lock")"
  echo "[setup] release_root=${RELEASE_ROOT}"
  echo "[setup] toolchain_lock=${lock_path}"
  echo "[setup] bin_prefix=/usr/local/bin"
  echo "[setup] managed: terragrunt>=${TERRAGRUNT_VERSION} kubectl>=${KUBECTL_VERSION}"
  echo "[setup] external: terraform>=${TERRAFORM_VERSION} packer>=${PACKER_VERSION} ansible-core>=${ANSIBLE_CORE_VERSION}"
}

have() { command -v "$1" >/dev/null 2>&1; }

progress() {
  echo "[hyops-progress] $1"
}

run_quiet_timeout() {
  local seconds="$1"
  shift
  timeout --foreground "${seconds}s" "$@" 2>/dev/null || true
}

detect_pkg_manager() {
  if have apt-get; then
    echo "apt"
    return 0
  fi
  if have dnf; then
    echo "dnf"
    return 0
  fi
  if have yum; then
    echo "yum"
    return 0
  fi
  echo "ERR: unsupported package manager (expected apt-get, dnf, or yum)" >&2
  exit 2
}

PKG_MANAGER="$(detect_pkg_manager)"
PKG_UPDATED=0

if [[ "${PKG_MANAGER}" == "apt" ]]; then
  export DEBIAN_FRONTEND=noninteractive
fi

pkg_update_once() {
  if [[ "${PKG_UPDATED}" -eq 0 ]]; then
    case "${PKG_MANAGER}" in
      apt)
        apt-get update -y
        ;;
      dnf)
        dnf -y makecache
        ;;
      yum)
        yum -y makecache
        ;;
    esac
    PKG_UPDATED=1
  fi
}

pkg_install() {
  pkg_update_once
  case "${PKG_MANAGER}" in
    apt)
      apt-get install -y "$@"
      ;;
    dnf)
      dnf install -y "$@"
      ;;
    yum)
      yum install -y "$@"
      ;;
  esac
}

pkg_install_optional() {
  pkg_install "$@" >/dev/null 2>&1
}

ensure_foundation() {
  case "${PKG_MANAGER}" in
    apt)
      pkg_install ca-certificates curl gnupg lsb-release openssh-client unzip
      ;;
    dnf|yum)
      pkg_install ca-certificates curl gnupg2 openssh-clients unzip tar
      ;;
  esac
}

ensure_python() {
  case "${PKG_MANAGER}" in
    apt)
      pkg_install python3 python3-venv python3-pip
      ;;
    dnf|yum)
      pkg_install python3 python3-pip
      ;;
  esac
}

_install_bin_raw() {
  local name="$1"
  local url="$2"
  local dest="/usr/local/bin/${name}"

  curl --fail --silent --show-error --location \
    --connect-timeout 15 --max-time 300 \
    --retry 5 --retry-delay 2 --retry-all-errors \
    -o "${dest}" "${url}"
  chmod 0755 "${dest}"
}

_arch() {
  local arch=""
  arch="$(uname -m)"
  case "${arch}" in
    amd64|x86_64) echo "amd64" ;;
    arm64|aarch64) echo "arm64" ;;
    *) echo "ERR: unsupported architecture: ${arch}" >&2; exit 2 ;;
  esac
}

_version_fail() {
  local name="$1"
  local expected="$2"
  local actual="$3"
  echo "ERR: ${name} version unsupported (required=${expected} actual=${actual})." >&2
  echo "ERR: Ensure the required ${name} is first on PATH, or rerun: hyops setup base --sudo" >&2
  exit 2
}

terragrunt_version() {
  local terragrunt_bin=""
  terragrunt_bin="$(tool_cmd_path terragrunt)"
  [[ -n "${terragrunt_bin}" ]] || return 0
  run_quiet_timeout 20 "${terragrunt_bin}" --version | head -n1 | sed -E 's/^terragrunt version v//; s/[[:space:]].*$//' || true
}

kubectl_version() {
  local out v
  local kubectl_bin=""
  kubectl_bin="$(tool_cmd_path kubectl)"
  [[ -n "${kubectl_bin}" ]] || return 0
  out="$(run_quiet_timeout 20 "${kubectl_bin}" version --client | tr -d '\r' || true)"

  # Preferred (modern) format:
  #   Client Version: v1.30.7
  v="$(printf '%s\n' "${out}" | sed -nE 's/^Client Version:[[:space:]]*v?([0-9]+(\.[0-9]+)+).*/\1/p' | head -n1)"
  if [[ -n "${v}" ]]; then
    echo "${v}"
    return 0
  fi

  # Fallback (older) format:
  #   ... GitVersion:"v1.30.7" ...
  v="$(printf '%s\n' "${out}" | sed -nE 's/.*GitVersion:\"v?([0-9]+(\.[0-9]+)+)\".*/\1/p' | head -n1)"
  echo "${v}"
}

ensure_terragrunt() {
  local v arch url
  v="$(toolchain_require TERRAGRUNT_VERSION)"
  if [[ -n "$(tool_cmd_path terragrunt)" ]]; then
    local actual path
    actual="$(terragrunt_version)"
    path="$(tool_cmd_path terragrunt)"
    if ver_ok_min_same_major "${actual}" "${v}"; then
      echo "[setup] terragrunt ok (v${actual:-unknown} at ${path:-unknown})"
      return 0
    fi
    echo "[setup] terragrunt too old/unsupported (found v${actual:-unknown} at ${path:-unknown}); installing v${v}"
  else
    echo "[setup] terragrunt installing v${v}"
  fi
  ensure_foundation
  arch="$(_arch)"
  url="https://github.com/gruntwork-io/terragrunt/releases/download/v${v}/terragrunt_linux_${arch}"
  _install_bin_raw "terragrunt" "${url}"
  local actual_final
  actual_final="$(terragrunt_version)"
  ver_ok_min_same_major "${actual_final}" "${v}" || _version_fail "terragrunt" ">=${v}" "${actual_final:-unknown}"
  echo "[setup] terragrunt ok (v${actual_final:-unknown} at $(cmd_path terragrunt))"
}

ensure_kubectl() {
  local v arch url
  v="$(toolchain_require KUBECTL_VERSION)"
  if [[ -n "$(tool_cmd_path kubectl)" ]]; then
    local actual path
    actual="$(kubectl_version)"
    path="$(tool_cmd_path kubectl)"
    if ver_ok_min_same_major "${actual}" "${v}"; then
      echo "[setup] kubectl ok (v${actual:-unknown} at ${path:-unknown})"
      return 0
    fi
    echo "[setup] kubectl too old/unsupported (found v${actual:-unknown} at ${path:-unknown}); installing v${v}"
  else
    echo "[setup] kubectl installing v${v}"
  fi
  ensure_foundation
  arch="$(_arch)"
  url="https://dl.k8s.io/release/v${v}/bin/linux/${arch}/kubectl"
  _install_bin_raw "kubectl" "${url}"
  local actual_final
  actual_final="$(kubectl_version)"
  ver_ok_min_same_major "${actual_final}" "${v}" || _version_fail "kubectl" ">=${v}" "${actual_final:-unknown}"
  echo "[setup] kubectl ok (v${actual_final:-unknown} at $(cmd_path kubectl))"
}

ensure_gh() {
  have gh && return 0
  if pkg_install_optional gh; then
    return 0
  fi
  echo "[setup] gh unavailable from configured package repositories; skipping"
}

ensure_vault_pass_deps() {
  ensure_foundation
  case "${PKG_MANAGER}" in
    apt)
      pkg_install pass pinentry-curses
      ;;
    dnf|yum)
      pkg_install pass pinentry
      ;;
  esac
  have pass || {
    echo "ERR: pass was installed but is not available on PATH" >&2
    exit 1
  }
  if ! have pinentry && ! have pinentry-curses && ! have pinentry-tty; then
    echo "ERR: pinentry was installed but is not available on PATH" >&2
    exit 1
  fi
}

main() {
  toolchain__load
  print_header
  progress "Refreshing package information"
  pkg_update_once
  progress "Installing system utilities"
  ensure_foundation
  progress "Installing Python runtime"
  ensure_python
  progress "Installing managed runtime"
  ensure_terragrunt
  ensure_kubectl
  progress "Checking external executors"
  hyops_setup_verify_external_executors \
    "${TERRAFORM_VERSION}" "${PACKER_VERSION}" "${ANSIBLE_CORE_VERSION}"
  progress "Installing supporting components"
  ensure_gh
  ensure_vault_pass_deps
  progress "Verifying base setup"
  echo "[setup] base ready"
}

main "$@"
