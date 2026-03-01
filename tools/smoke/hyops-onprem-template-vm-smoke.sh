#!/usr/bin/env bash
# purpose: Run an end-to-end smoke chain (init -> template-image linux/windows -> platform-vm) using the public hyops CLI path.
# Architecture Decision: ADR-0206 (module execution contract v1)

set -euo pipefail

usage() {
  cat <<'USAGE'
usage: hyops-onprem-template-vm-smoke.sh --proxmox-ip <ip> [options]

options:
  --env <name>                       Runtime environment namespace (default: dev)
  --root <path>                      Runtime root override (default: ~/.hybridops)
  --hyops-bin <path>                 HyOps CLI path (default: hyops)
  --proxmox-ip <ip>                  Proxmox API host used by init
  --vault-password-command <cmd>     Vault password command for init (optional)
  --linux-key <template_key>         Linux template key (default: ubuntu-24.04)
  --windows-key <template_key>       Windows template key (default: windows-11-enterprise)
  --skip-init                        Skip hyops init proxmox
  --skip-windows                     Skip Windows template build
  --vm-name-prefix <prefix>          Prefix for smoke VM name (default: smoke-vm)
  --bridge <name>                    Proxmox bridge for smoke VM NIC (default: vmbr0)
  --state-instance <name>            Isolated platform-vm state slot for smoke (default: template_smoke_vm)
  --keep-vm                          Do not destroy smoke VM after successful run
  -h, --help                         Show this helper
USAGE
}

env_name="dev"
runtime_root=""
hyops_bin="hyops"
proxmox_ip=""
vault_password_command=""
linux_key="ubuntu-24.04"
windows_key="windows-11-enterprise"
run_init="true"
run_windows="true"
vm_name_prefix="smoke-vm"
bridge_name="vmbr0"
smoke_state_instance="template_smoke_vm"
keep_vm="false"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --env)
      env_name="$2"
      shift 2
      ;;
    --root)
      runtime_root="$2"
      shift 2
      ;;
    --hyops-bin)
      hyops_bin="$2"
      shift 2
      ;;
    --proxmox-ip)
      proxmox_ip="$2"
      shift 2
      ;;
    --vault-password-command)
      vault_password_command="$2"
      shift 2
      ;;
    --linux-key)
      linux_key="$2"
      shift 2
      ;;
    --windows-key)
      windows_key="$2"
      shift 2
      ;;
    --skip-init)
      run_init="false"
      shift
      ;;
    --skip-windows)
      run_windows="false"
      shift
      ;;
    --vm-name-prefix)
      vm_name_prefix="$2"
      shift 2
      ;;
    --bridge)
      bridge_name="$2"
      shift 2
      ;;
    --state-instance)
      smoke_state_instance="$2"
      shift 2
      ;;
    --keep-vm)
      keep_vm="true"
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "error: unknown argument: $1" >&2
      usage
      exit 2
      ;;
  esac
done

if [[ "$run_init" == "true" && -z "$proxmox_ip" ]]; then
  echo "error: --proxmox-ip is required unless --skip-init is set" >&2
  exit 2
fi

if ! command -v "$hyops_bin" >/dev/null 2>&1; then
  echo "error: hyops not found (or not executable): $hyops_bin" >&2
  echo "hint: install hyops or pass --hyops-bin /path/to/hyops" >&2
  exit 2
fi

root_args=()
if [[ -n "$runtime_root" ]]; then
  root_args=(--root "$runtime_root")
fi

vault_args=()
if [[ -n "$vault_password_command" ]]; then
  vault_args=(--vault-password-command "$vault_password_command")
fi

timestamp="$(date -u +%Y%m%dT%H%M%SZ)"
scratch="/tmp/hyops-smoke-${env_name}-${timestamp}"
mkdir -p "$scratch"

linux_name="${env_name}-${linux_key//./-}-template"
windows_name="${env_name}-${windows_key//./-}-template"
vm_name="${vm_name_prefix}-${env_name}-$(date -u +%H%M%S)"

linux_inputs="${scratch}/template-linux.yml"
windows_inputs="${scratch}/template-windows.yml"
vm_inputs="${scratch}/platform-vm.yml"

cat >"$linux_inputs" <<EOF
template_key: "${linux_key}"
rebuild_if_exists: true
name: "${linux_name}"
EOF

cat >"$windows_inputs" <<EOF
template_key: "${windows_key}"
rebuild_if_exists: true
name: "${windows_name}"
EOF

cat >"$vm_inputs" <<EOF
template_state_ref: "core/onprem/template-image"
template_key: "${linux_key}"
require_ipam: false
vms:
  ${vm_name}:
    role: "smoke"
    interfaces:
      - bridge: "${bridge_name}"
        ipv4:
          address: "dhcp"
EOF

cleanup_vm() {
  if [[ "$keep_vm" == "true" ]]; then
    return 0
  fi
  if [[ ! -f "$vm_inputs" ]]; then
    return 0
  fi
  set +e
  "$hyops_bin" destroy "${root_args[@]}" --env "$env_name" \
    --module platform/onprem/platform-vm \
    --state-instance "$smoke_state_instance" \
    --inputs "$vm_inputs" \
    --skip-preflight >/dev/null 2>&1
  set -e
}
trap cleanup_vm EXIT INT TERM

if [[ "$run_init" == "true" ]]; then
  "$hyops_bin" init proxmox "${root_args[@]}" --env "$env_name" "${vault_args[@]}" --bootstrap --proxmox-ip "$proxmox_ip"
fi

if [[ "$run_windows" == "true" ]]; then
  "$hyops_bin" preflight "${root_args[@]}" --env "$env_name" --strict \
    --module core/onprem/template-image --inputs "$windows_inputs"
  "$hyops_bin" apply "${root_args[@]}" --env "$env_name" --module core/onprem/template-image --inputs "$windows_inputs"
fi

"$hyops_bin" preflight "${root_args[@]}" --env "$env_name" --strict \
  --module core/onprem/template-image --inputs "$linux_inputs"
"$hyops_bin" apply "${root_args[@]}" --env "$env_name" --module core/onprem/template-image --inputs "$linux_inputs"

"$hyops_bin" preflight "${root_args[@]}" --env "$env_name" --strict \
  --module platform/onprem/platform-vm --state-instance "$smoke_state_instance" --inputs "$vm_inputs"
"$hyops_bin" apply "${root_args[@]}" --env "$env_name" \
  --module platform/onprem/platform-vm \
  --state-instance "$smoke_state_instance" \
  --inputs "$vm_inputs"

resolved_root="${runtime_root:-$HOME/.hybridops}"
template_state_path="${resolved_root}/envs/${env_name}/state/modules/core__onprem__template-image/latest.json"
vm_state_path="${resolved_root}/envs/${env_name}/state/modules/platform__onprem__platform-vm/instances/${smoke_state_instance}.json"
verify_out="${scratch}/smoke-vm-verify.env"

python3 - "$vm_state_path" "$vm_name" >"$verify_out" <<'PY'
import json
import sys
from pathlib import Path

state_path = Path(sys.argv[1]).expanduser()
vm_name = str(sys.argv[2])

if not state_path.exists():
    raise SystemExit(f"error: expected platform-vm instance state not found: {state_path}")

payload = json.loads(state_path.read_text(encoding="utf-8"))
state_status = str(payload.get("status") or "").strip().lower()
if state_status != "ok":
    raise SystemExit(f"error: platform-vm smoke state is not ok (status={state_status or 'unknown'})")

outputs = payload.get("outputs")
if not isinstance(outputs, dict):
    raise SystemExit("error: platform-vm smoke state missing outputs map")

vms = outputs.get("vms")
if not isinstance(vms, dict):
    raise SystemExit("error: platform-vm smoke state missing outputs.vms map")

vm = vms.get(vm_name)
if not isinstance(vm, dict):
    available = ",".join(sorted(str(k) for k in vms.keys())) if vms else "<none>"
    raise SystemExit(
        f"error: smoke VM '{vm_name}' not found in outputs.vms (available={available})"
    )

vm_id = vm.get("vm_id")
if vm_id in (None, ""):
    vm_id = vm.get("id")
if vm_id in (None, ""):
    raise SystemExit(f"error: smoke VM '{vm_name}' missing vm_id/id in outputs.vms")

ip = str(vm.get("ip_address") or "").strip()
if not ip:
    ip_map = outputs.get("ip_addresses")
    if isinstance(ip_map, dict):
        ip = str(ip_map.get(vm_name) or "").strip()

vm_status = str(vm.get("status") or "").strip()

print("smoke_verify=ok")
print(f"smoke_vm_name={vm_name}")
print(f"smoke_vm_id={vm_id}")
print(f"smoke_vm_ip={ip}")
print(f"smoke_vm_ip_present={'true' if bool(ip) else 'false'}")
print(f"smoke_vm_record_status={vm_status}")
print(f"smoke_vm_state_path={state_path}")
PY

cat <<EOF
smoke_status=ok
env=${env_name}
scratch=${scratch}
runtime_root=${resolved_root}
template_state=${template_state_path}
vm_state=${vm_state_path}
vm_state_latest=${resolved_root}/envs/${env_name}/state/modules/platform__onprem__platform-vm/latest.json
module_logs=${resolved_root}/envs/${env_name}/logs/module
cleanup=${keep_vm}
EOF
cat "$verify_out"
