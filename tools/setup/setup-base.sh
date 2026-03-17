#!/usr/bin/env bash
# purpose: Install base system prerequisites for HybridOps.Core (pinned toolchain).
# Architecture Decision: ADR-N/A
# maintainer: HybridOps.Tech

set -euo pipefail

[[ "${EUID}" -eq 0 ]] || { echo "ERR: requires root (use: hyops setup base --sudo)"; exit 2; }

export PATH="/usr/local/bin:/usr/local/sbin:${PATH}"

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
RELEASE_ROOT="$(cd -- "${SCRIPT_DIR}/../.." && pwd)"

# shellcheck source=/dev/null
source "${RELEASE_ROOT}/tools/setup/lib/toolchain_lock.sh"

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

ver_ge() {
  local actual="${1#v}"
  local expected="${2#v}"
  local highest=""
  [[ -n "${actual}" && -n "${expected}" ]] || return 1
  highest="$(printf '%s\n%s\n' "${actual}" "${expected}" | sort -V | tail -n1)"
  [[ "${highest}" == "${actual}" ]]
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

have() { command -v "$1" >/dev/null 2>&1; }

run_quiet_timeout() {
  local seconds="$1"
  shift
  timeout --foreground "${seconds}s" "$@" 2>/dev/null || true
}

python_cmd_version() {
  local python_cmd="$1"
  "${python_cmd}" - <<'PY' 2>/dev/null || true
import sys
print(".".join(str(v) for v in sys.version_info[:3]))
PY
}

ansible_core_min_python_version() {
  local core_v="${1#v}"
  local mm=""
  mm="$(printf '%s' "${core_v}" | cut -d. -f1-2)"
  case "${mm}" in
    2.20) echo "3.12" ;;
    2.18|2.19) echo "3.11" ;;
    2.16|2.17) echo "3.10" ;;
    *) echo "3.9" ;;
  esac
}

ensure_ansible_python_runtime() {
  local core_v="$1"
  local min_python=""
  local current_python=""
  local current_version=""
  local alt_python=""
  local alt_version=""

  min_python="$(ansible_core_min_python_version "${core_v}")"
  current_python="$(cmd_path python3)"
  current_version="$(python_cmd_version "${current_python}")"
  if ver_ge "${current_version}" "${min_python}"; then
    echo "${current_python}"
    return 0
  fi

  case "${PKG_MANAGER}" in
    apt)
      pkg_install "python${min_python}" "python${min_python}-venv" >&2
      alt_python="$(cmd_path "python${min_python}")"
      ;;
    dnf|yum)
      pkg_install "python${min_python}" >&2
      alt_python="$(cmd_path "python${min_python}")"
      ;;
  esac

  alt_version="$(python_cmd_version "${alt_python}")"
  ver_ge "${alt_version}" "${min_python}" || {
    echo "ERR: unable to provision Python >=${min_python} required for ansible-core ${core_v}" >&2
    exit 2
  }
  echo "${alt_python}"
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

ensure_pipx() {
  if have pipx; then
    return 0
  fi

  # Prefer distro package.
  if pkg_install_optional pipx; then
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
  curl --fail --silent --show-error --location \
    --connect-timeout 15 --max-time 300 \
    --retry 5 --retry-delay 2 --retry-all-errors \
    -o "${tmp}/${name}.zip" "${url}"
  (cd "${tmp}" && unzip -qq "${name}.zip")
  install -m 0755 "${tmp}/${name}" "${dest}"
  rm -rf "${tmp}"
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

terraform_version() {
  local terraform_bin=""
  terraform_bin="$(tool_cmd_path terraform)"
  [[ -n "${terraform_bin}" ]] || return 0
  run_quiet_timeout 20 "${terraform_bin}" version | head -n1 | sed -E 's/^Terraform v//; s/[[:space:]].*$//' || true
}

packer_version() {
  local packer_bin="" resolved=""
  packer_bin="$(tool_cmd_path packer)"
  [[ -n "${packer_bin}" ]] || return 0
  resolved="$(readlink -f "${packer_bin}" 2>/dev/null || printf '%s' "${packer_bin}")"
  if [[ "${resolved}" == *"/cracklib-packer" ]]; then
    return 0
  fi
  run_quiet_timeout 20 "${packer_bin}" version | head -n1 | sed -E 's/^Packer v//; s/[[:space:]].*$//' || true
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

ansible_core_version() {
  # Ansible CLI reports the ansible-core version on line 1:
  #   ansible [core 2.16.14]
  # Avoid relying on ~/.ansible/tmp, which may have restrictive permissions on
  # some workstations due to prior root/CI runs.
  have ansible || return 0

  local line
  line="$(ANSIBLE_LOCAL_TEMP=/tmp/hyops-ansible-local run_quiet_timeout 20 ansible --version | head -n1 | tr -d '\r' || true)"

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
    path="$(tool_cmd_path terraform)"
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
  if [[ -n "$(tool_cmd_path packer)" ]]; then
    local actual path
    actual="$(packer_version)"
    path="$(tool_cmd_path packer)"
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

ensure_ansible() {
  local ansible_v core_v ansible_python

  core_v="$(toolchain_require ANSIBLE_CORE_VERSION)"
  ansible_v="$(toolchain_get ANSIBLE_VERSION)"
  ansible_python="$(ensure_ansible_python_runtime "${core_v}" | tail -n1)"

  echo "[setup] ansible: ensuring pinned version"

  # Some upstream roles require controller-side Python deps (json_query/netaddr)
  # at playbook parse time, even for tasks that will later be skipped.
  ensure_python
  if ! pkg_install_optional python3-jmespath python3-netaddr; then
    echo "[setup] python3-jmespath/python3-netaddr not available from package manager; relying on pipx injection"
  fi

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
    pipx install --python "${ansible_python}" "ansible==${ansible_v}" --include-deps --force 2>&1 | filter_pipx_output
  else
    pipx install --python "${ansible_python}" "ansible-core==${core_v}" --include-deps --force 2>&1 | filter_pipx_output
  fi

  have ansible && have ansible-galaxy || { echo "ERR: ansible install failed"; exit 2; }
  require_ansible_core_version "${core_v}"
  pipx inject ansible jmespath netaddr --force 2>&1 | filter_pipx_output || true
  pipx inject ansible-core jmespath netaddr --force 2>&1 | filter_pipx_output || true
  echo "[setup] ansible-core ok (core>=$(ansible_core_version) at $(cmd_path ansible))"
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
      if pkg_install_optional pass pinentry-curses; then
        return 0
      fi
      ;;
    dnf|yum)
      if pkg_install_optional pass pinentry; then
        return 0
      fi
      ;;
  esac
  echo "[setup] pass/pinentry unavailable from configured package repositories; skipping"
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
