#!/usr/bin/env bash
# purpose: Verify the operator-supplied executor boundary in base setup.
# adr: ADR-N/A
# maintainer: HybridOps.Tech

set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd -- "${SCRIPT_DIR}/../.." && pwd)"
LINUX_SETUP="${REPO_ROOT}/tools/setup/setup-base.sh"
MACOS_SETUP="${REPO_ROOT}/tools/setup/setup-base-macos.sh"
SETUP_ROOT="${REPO_ROOT}/tools/setup"
EXECUTOR_LIB="${REPO_ROOT}/tools/setup/lib/external_executors.sh"

if grep -Eq \
  'releases\.hashicorp\.com/(terraform|packer)|hashicorp/tap|(pip|pipx).*install.*(ansible|ansible-core)|(apt-get|dnf|yum|brew).*install.*(terraform|packer|ansible)' \
  "${LINUX_SETUP}" "${MACOS_SETUP}" "${SETUP_ROOT}/lib/"*.sh; then
  echo "ERR: base setup installs an operator-supplied executor" >&2
  exit 1
fi

work_dir="$(mktemp -d)"
trap 'rm -rf "${work_dir}"' EXIT
fake_bin="${work_dir}/bin"
mkdir -p "${fake_bin}"

cat >"${fake_bin}/terraform" <<'EOF'
#!/bin/bash
echo 'Terraform v1.10.5'
EOF
cat >"${fake_bin}/packer" <<'EOF'
#!/bin/bash
echo 'Packer v1.11.1'
EOF
for command_name in ansible ansible-playbook ansible-galaxy ansible-vault; do
  cat >"${fake_bin}/${command_name}" <<'EOF'
#!/bin/bash
echo 'ansible [core 2.18.0]'
EOF
done
chmod 0755 "${fake_bin}"/*

for support_command in python3 head sed tr readlink timeout; do
  support_path="$(command -v "${support_command}" 2>/dev/null || true)"
  if [[ -n "${support_path}" ]]; then
    ln -s "${support_path}" "${fake_bin}/${support_command}"
  fi
done

PATH="${fake_bin}" \
  /bin/bash -c 'source "$1"; hyops_setup_verify_external_executors 1.10.5 1.11.1 2.18.0' \
  _ "${EXECUTOR_LIB}" >"${work_dir}/ready.out"
grep -Fq '[setup] terraform ok' "${work_dir}/ready.out"
grep -Fq '[setup] packer ok' "${work_dir}/ready.out"
grep -Fq '[setup] ansible-core ok' "${work_dir}/ready.out"

rm "${fake_bin}/packer"
set +e
PATH="${fake_bin}" \
  /bin/bash -c 'source "$1"; hyops_setup_verify_external_executors 1.10.5 1.11.1 2.18.0' \
  _ "${EXECUTOR_LIB}" >"${work_dir}/missing.out" 2>&1
missing_rc=$?
set -e
[[ "${missing_rc}" -eq 2 ]]
grep -Fq 'ERR: packer unavailable on PATH' "${work_dir}/missing.out"
grep -Fq 'required operator-supplied executors are not ready' "${work_dir}/missing.out"

cat >"${fake_bin}/packer" <<'EOF'
#!/bin/bash
echo 'Packer v1.11.1'
EOF
cat >"${fake_bin}/terraform" <<'EOF'
#!/bin/bash
echo 'Terraform v2.0.0'
EOF
chmod 0755 "${fake_bin}/packer" "${fake_bin}/terraform"
set +e
PATH="${fake_bin}" \
  /bin/bash -c 'source "$1"; hyops_setup_verify_external_executors 1.10.5 1.11.1 2.18.0' \
  _ "${EXECUTOR_LIB}" >"${work_dir}/unsupported.out" 2>&1
unsupported_rc=$?
set -e
[[ "${unsupported_rc}" -eq 2 ]]
grep -Fq 'required=>=1.10.5,<2.0.0 actual=2.0.0' "${work_dir}/unsupported.out"
