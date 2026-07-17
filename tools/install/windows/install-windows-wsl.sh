#!/usr/bin/env bash
set -euo pipefail
# purpose: Complete the Windows bootstrap inside Ubuntu on WSL2.
# maintainer: HybridOps.Tech

archive="${1:-}"
force_install="${2:-false}"

[[ -f "${archive}" ]] || {
  echo "ERR: release archive not found: ${archive}" >&2
  exit 2
}

if ! python3 -c 'import ensurepip' >/dev/null 2>&1; then
  echo "[windows] installing the Ubuntu Python virtual-environment prerequisite"
  sudo apt-get update
  sudo apt-get install -y python3-venv
fi

checksum="${archive}.sha256"
if [[ -f "${checksum}" ]]; then
  (
    cd "$(dirname -- "${archive}")"
    sha256sum -c "$(basename -- "${checksum}")"
  )
else
  echo "WARN: matching .sha256 file not found; release checksum was not verified" >&2
fi

install_root="${HOME}/hybridops/windows-install"
archive_list="$(mktemp)"
cleanup() {
  rm -f "${archive_list}"
}
trap cleanup EXIT

tar -tzf "${archive}" >"${archive_list}"
package_dir="$(awk -F/ 'NF {print $1; exit}' "${archive_list}")"
[[ -n "${package_dir}" ]] || {
  echo "ERR: release archive is empty" >&2
  exit 2
}

mkdir -p "${install_root}"
rm -rf "${install_root:?}/${package_dir}"
tar -xzf "${archive}" -C "${install_root}"
cd "${install_root}/${package_dir}"

args=()
if [[ "${force_install}" == "true" ]]; then
  args+=(--force)
fi

launcher_rc="${HOME}/.hybridops/config/windows-shell.rc"
mkdir -p "$(dirname -- "${launcher_rc}")"
cat >"${launcher_rc}" <<'EOF'
if [[ -f "${HOME}/.bashrc" ]]; then
  source "${HOME}/.bashrc"
fi
PS1='\[\033[36m\]hyops\[\033[0m\]:\[\033[34m\]\w\[\033[0m\]\$ '
EOF
chmod 0600 "${launcher_rc}"

exec ./install.sh "${args[@]}"
