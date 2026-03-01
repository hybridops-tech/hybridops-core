#!/usr/bin/env bash
# purpose: Install base system prerequisites for HybridOps.Core (pinned toolchain).
# Architecture Decision: ADR-N/A
# maintainer: HybridOps.Studio

set -euo pipefail

[[ "${EUID}" -eq 0 ]] || { echo "ERR: requires root (use: hyops setup base --sudo)"; exit 2; }

export DEBIAN_FRONTEND=noninteractive

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
RELEASE_ROOT="$(cd -- "${SCRIPT_DIR}/../.." && pwd)"

# shellcheck source=/dev/null
source "${RELEASE_ROOT}/tools/setup/lib/toolchain_lock.sh"

cmd_path() { command -v "$1" 2>/dev/null || true; }

ver_major() {
  local v="${1#v}"
  echo "${v%%.*}"
}

ver_ok_min_same_major() {
  local actual="${1#v}"
  local expected="${2#v}"
  [[ -n "${actual}" && -n "${expected}" ]] || return 1
  [[ "$(ver_major "${actual}")" == "$(ver_major "${expected}")" ]] || return 1
  dpkg --compare-versions "${actual}" ge "${expected}"
}

print_header() {
  local lock_path
  lock_path="$(toolchain__lock_path 2>/dev/null || echo "${RELEASE_ROOT}/tools/setup/requirements/toolchain.lock")"
  echo "[setup] release_root=${RELEASE_ROOT}"
  echo "[setup] toolchain_lock=${lock_path}"
  echo "[setup] bin_prefix=/usr/local/bin"
  echo "[setup] required: terraform>=${TERRAFORM_VERSION} terragrunt>=${TERRAGRUNT_VERSION} packer>=${PACKER_VERSION} kubectl>=${KUBECTL_VERSION} ansible-core>=${ANSIBLE_CORE_VERSION}"
}

# Keep setup output readable: show installs, but suppress noisy pipx chatter and emojis.
filter_pipx_output() {
  # Strip non-ASCII (including emojis) first, then drop known-noise lines.
  LC_ALL=C tr -cd '\11\12\15\40-\176' | awk '
    BEGIN { skip_apps = 0 }
    /already on your PATH at/ { next }
    /^done!/ { next }
    /These apps are now globally available/ { skip_apps = 1; next }
    skip_apps {
      if ($0 ~ /^[[:space:]]*-[[:space:]]+/) { next }
      skip_apps = 0
    }
    { print }
  '
}

APT_UPDATED=0

apt_update_once() {
  if [[ "${APT_UPDATED}" -eq 0 ]]; then
    apt-get update -y
    APT_UPDATED=1
  fi
}

apt_install() {
  apt_update_once
  apt-get install -y "$@"
}

have() { command -v "$1" >/dev/null 2>&1; }

ensure_foundation() {
  apt_install ca-certificates curl gnupg lsb-release openssh-client unzip
}

ensure_python() {
  apt_install python3 python3-venv python3-pip
}

ensure_pipx() {
  if have pipx; then
    return 0
  fi

  # Prefer distro package.
  if apt_install pipx; then
    :
  else
    python3 -m pip install --no-input --upgrade pip >/dev/null 2>&1 || true
    python3 -m pip install --no-input --upgrade pipx
  fi

  have pipx || { echo "ERR: pipx install failed"; exit 2; }
}

_install_bin_zip() {
  local name="$1"
  local url="$2"
  local dest="/usr/local/bin/${name}"

  local tmp
  tmp="$(mktemp -d)"
  curl -fsSL -o "${tmp}/${name}.zip" "${url}"
  (cd "${tmp}" && unzip -qq "${name}.zip")
  install -m 0755 "${tmp}/${name}" "${dest}"
  rm -rf "${tmp}"
}

_install_bin_raw() {
  local name="$1"
  local url="$2"
  local dest="/usr/local/bin/${name}"

  curl -fsSLo "${dest}" "${url}"
  chmod 0755 "${dest}"
}

_arch() {
  local arch
  arch="$(dpkg --print-architecture)"
  case "${arch}" in
    amd64) echo "amd64" ;;
    arm64) echo "arm64" ;;
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

terraform_version() {
  terraform version 2>/dev/null | head -n1 | sed -E 's/^Terraform v//; s/[[:space:]].*$//' || true
}

packer_version() {
  packer version 2>/dev/null | head -n1 | sed -E 's/^Packer v//; s/[[:space:]].*$//' || true
}

terragrunt_version() {
  terragrunt --version 2>/dev/null | head -n1 | sed -E 's/^terragrunt version v//; s/[[:space:]].*$//' || true
}

kubectl_version() {
  local out v
  out="$(kubectl version --client 2>/dev/null | tr -d '\r' || true)"

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

ansible_core_version() {
  # Ansible CLI reports the ansible-core version on line 1:
  #   ansible [core 2.16.14]
  # Avoid relying on ~/.ansible/tmp, which may have restrictive permissions on
  # some workstations due to prior root/CI runs.
  have ansible || return 0

  local line
  line="$(ANSIBLE_LOCAL_TEMP=/tmp/hyops-ansible-local ansible --version 2>/dev/null | head -n1 | tr -d '\r' || true)"

  if [[ "${line}" =~ \[core[[:space:]]+([0-9]+(\.[0-9]+)+)\] ]]; then
    echo "${BASH_REMATCH[1]}"
    return 0
  fi

  # Fallback for older/alternate formats, best-effort.
  if [[ "${line}" =~ ^ansible(-core)?[[:space:]]+([0-9]+(\.[0-9]+)+) ]]; then
    echo "${BASH_REMATCH[2]}"
    return 0
  fi

  echo ""
}

check_ansible_core_version() {
  local expected_core="$1"
  local actual
  actual="$(ansible_core_version)"
  ver_ok_min_same_major "${actual}" "${expected_core}"
}

require_ansible_core_version() {
  local expected_core="$1"
  local actual
  actual="$(ansible_core_version)"
  ver_ok_min_same_major "${actual}" "${expected_core}" || _version_fail "ansible-core" ">=${expected_core}" "${actual:-unknown}"
}

ensure_terraform() {
  local v arch url
  v="$(toolchain_require TERRAFORM_VERSION)"
  if have terraform; then
    local actual path
    actual="$(terraform_version)"
    path="$(cmd_path terraform)"
    if ver_ok_min_same_major "${actual}" "${v}"; then
      echo "[setup] terraform ok (v${actual:-unknown} at ${path:-unknown})"
      return 0
    fi
    echo "[setup] terraform too old/unsupported (found v${actual:-unknown} at ${path:-unknown}); installing v${v}"
  else
    echo "[setup] terraform installing v${v}"
  fi
  ensure_foundation
  arch="$(_arch)"
  url="https://releases.hashicorp.com/terraform/${v}/terraform_${v}_linux_${arch}.zip"
  _install_bin_zip "terraform" "${url}"
  local actual_final
  actual_final="$(terraform_version)"
  ver_ok_min_same_major "${actual_final}" "${v}" || _version_fail "terraform" ">=${v}" "${actual_final:-unknown}"
  echo "[setup] terraform ok (v${actual_final:-unknown} at $(cmd_path terraform))"
}

ensure_packer() {
  local v arch url
  v="$(toolchain_require PACKER_VERSION)"
  if have packer; then
    local actual path
    actual="$(packer_version)"
    path="$(cmd_path packer)"
    if ver_ok_min_same_major "${actual}" "${v}"; then
      echo "[setup] packer ok (v${actual:-unknown} at ${path:-unknown})"
      return 0
    fi
    echo "[setup] packer too old/unsupported (found v${actual:-unknown} at ${path:-unknown}); installing v${v}"
  else
    echo "[setup] packer installing v${v}"
  fi
  ensure_foundation
  arch="$(_arch)"
  url="https://releases.hashicorp.com/packer/${v}/packer_${v}_linux_${arch}.zip"
  _install_bin_zip "packer" "${url}"
  local actual_final
  actual_final="$(packer_version)"
  ver_ok_min_same_major "${actual_final}" "${v}" || _version_fail "packer" ">=${v}" "${actual_final:-unknown}"
  echo "[setup] packer ok (v${actual_final:-unknown} at $(cmd_path packer))"
}

ensure_terragrunt() {
  local v arch url
  v="$(toolchain_require TERRAGRUNT_VERSION)"
  if have terragrunt; then
    local actual path
    actual="$(terragrunt_version)"
    path="$(cmd_path terragrunt)"
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
  if have kubectl; then
    local actual path
    actual="$(kubectl_version)"
    path="$(cmd_path kubectl)"
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

ensure_ansible() {
  local ansible_v core_v

  core_v="$(toolchain_require ANSIBLE_CORE_VERSION)"
  ansible_v="$(toolchain_get ANSIBLE_VERSION)"

  echo "[setup] ansible: ensuring pinned version"

  # Some upstream roles require controller-side Python deps (json_query/netaddr)
  # at playbook parse time, even for tasks that will later be skipped.
  ensure_python
  apt_install python3-jmespath python3-netaddr

  # If Ansible is already installed but not pinned, do not fail; install/override
  # a pinned version via pipx instead (pipx installs into /usr/local/bin).
  if have ansible && have ansible-galaxy; then
    if check_ansible_core_version "${core_v}"; then
      echo "[setup] ansible-core ok (core>=$(ansible_core_version) at $(cmd_path ansible))"
      # Best-effort: when Ansible is installed via pipx, ensure required deps
      # inside the pipx environment too (system site-packages won't apply).
      if [[ "$(cmd_path ansible)" == "/usr/local/bin/ansible" ]] && have pipx; then
        export PIPX_HOME="${PIPX_HOME:-/opt/pipx}"
        export PIPX_BIN_DIR="${PIPX_BIN_DIR:-/usr/local/bin}"
        export PATH="${PIPX_BIN_DIR}:${PATH}"
        pipx inject ansible jmespath netaddr --force 2>&1 | filter_pipx_output || true
        pipx inject ansible-core jmespath netaddr --force 2>&1 | filter_pipx_output || true
      fi
      return 0
    fi
    local actual_core
    actual_core="$(ansible_core_version)"
    [[ -n "${actual_core}" ]] || actual_core="unknown"
    echo "[setup] ansible-core too old/unsupported (found ${actual_core}); installing pinned version"
  fi

  ensure_pipx

  export PIPX_HOME="${PIPX_HOME:-/opt/pipx}"
  export PIPX_BIN_DIR="${PIPX_BIN_DIR:-/usr/local/bin}"
  export PATH="${PIPX_BIN_DIR}:${PATH}"

  mkdir -p "${PIPX_HOME}" "${PIPX_BIN_DIR}"
  if [[ -n "${ansible_v}" ]]; then
    pipx install "ansible==${ansible_v}" --include-deps --force 2>&1 | filter_pipx_output
  else
    pipx install "ansible-core==${core_v}" --include-deps --force 2>&1 | filter_pipx_output
  fi

  have ansible && have ansible-galaxy || { echo "ERR: ansible install failed"; exit 2; }
  require_ansible_core_version "${core_v}"
  pipx inject ansible jmespath netaddr --force 2>&1 | filter_pipx_output || true
  pipx inject ansible-core jmespath netaddr --force 2>&1 | filter_pipx_output || true
  echo "[setup] ansible-core ok (core>=$(ansible_core_version) at $(cmd_path ansible))"
}

ensure_gh() {
  have gh && return 0
  apt_install gh
}

ensure_vault_pass_deps() {
  ensure_foundation
  apt_install pass pinentry-curses
}

main() {
  toolchain__load
  print_header
  ensure_foundation
  ensure_python
  ensure_ansible
  ensure_terraform
  ensure_terragrunt
  ensure_packer
  ensure_kubectl
  ensure_gh
  ensure_vault_pass_deps
  echo "[setup] base installed (pinned)"
}

main "$@"
