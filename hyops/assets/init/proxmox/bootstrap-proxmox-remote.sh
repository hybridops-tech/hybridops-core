#!/usr/bin/env bash
# purpose: Bootstrap a Proxmox host for HybridOps runtime credentials and discovery.
# Architecture Decision: ADR-N/A (init proxmox remote bootstrap)
# maintainer: HybridOps.Tech

set -euo pipefail

USER_FQ="${USER_FQ:?USER_FQ is required}"
TOKEN_NAME="${TOKEN_NAME:-infra-token}"
API_IP="${API_IP:-}"
FALLBACK_STORAGE_VM="${FALLBACK_STORAGE_VM:-local-lvm}"
FALLBACK_STORAGE_ISO="${FALLBACK_STORAGE_ISO:-local}"
FALLBACK_STORAGE_SNIPPETS="${FALLBACK_STORAGE_SNIPPETS:-$FALLBACK_STORAGE_ISO}"
FALLBACK_BRIDGE="${FALLBACK_BRIDGE:-vmbr0}"

log_info()  { printf 'INFO: %s\n' "$*" >&2; }
log_warn()  { printf 'WARN: %s\n' "$*" >&2; }
log_error() { printf 'ERROR: %s\n' "$*" >&2; }

command -v pveum >/dev/null 2>&1 || { log_error "pveum not found - is this a Proxmox host?"; exit 1; }
command -v pvesh >/dev/null 2>&1 || { log_error "pvesh not found - is this a Proxmox host?"; exit 1; }

USER="${USER_FQ%@*}"
REALM="${USER_FQ#*@}"
if [[ -z "${USER}" || -z "${REALM}" || "${USER_FQ}" != *"@"* ]]; then
  log_error "USER_FQ must be in the format user@realm"
  exit 1
fi
TOKEN_ID="${USER_FQ}!${TOKEN_NAME}"

NODE="$(hostname)"

if [[ -n "${API_IP}" ]]; then
  IP="${API_IP}"
else
  IP="$(ip -4 route get 1.1.1.1 2>/dev/null | awk '/src/ {for (i=1;i<=NF;i++) if ($i=="src") {print $(i+1); exit}}')" || true
  [[ -z "${IP}" ]] && IP="$(hostname -I | awk '{print $1}')" || true
fi

if [[ -z "${IP}" ]]; then
  log_error "Unable to determine API IP address"
  exit 1
fi

detect_store() {
  local want="$1"
  local sid
  for sid in $(pvesh get /storage --output-format json 2>/dev/null | sed -n 's/.*"storage":"\([^"]*\)".*/\1/p'); do
    if pvesh get "/storage/${sid}" --output-format json 2>/dev/null | grep -q "\"content\".*${want}"; then
      echo "${sid}"
      return 0
    fi
  done
  return 1
}

STORAGE_VM="$(detect_store images || true)"
STORAGE_ISO="$(detect_store iso || true)"
STORAGE_SNIPPETS="$(detect_store snippets || true)"
STORAGE_VM_SOURCE="detected"
STORAGE_ISO_SOURCE="detected"
STORAGE_SNIPPETS_SOURCE="detected"

if [[ -z "${STORAGE_VM}" ]]; then
  log_warn "Storage with 'images' not discovered; using fallback ${FALLBACK_STORAGE_VM}"
  STORAGE_VM="${FALLBACK_STORAGE_VM}"
  STORAGE_VM_SOURCE="configured"
fi
if [[ -z "${STORAGE_ISO}" ]]; then
  log_warn "Storage with 'iso' not discovered; using fallback ${FALLBACK_STORAGE_ISO}"
  STORAGE_ISO="${FALLBACK_STORAGE_ISO}"
  STORAGE_ISO_SOURCE="configured"
fi
if [[ -z "${STORAGE_SNIPPETS}" ]]; then
  log_warn "Storage with 'snippets' not discovered; using fallback ${FALLBACK_STORAGE_SNIPPETS}"
  STORAGE_SNIPPETS="${FALLBACK_STORAGE_SNIPPETS}"
  STORAGE_SNIPPETS_SOURCE="configured"
fi

BRIDGE_SOURCE="detected"

if [[ -n "${FALLBACK_BRIDGE}" ]] && ip link show "${FALLBACK_BRIDGE}" >/dev/null 2>&1 && ip link show "${FALLBACK_BRIDGE}" | grep -q "state UP"; then
  BRIDGE="${FALLBACK_BRIDGE}"
  BRIDGE_SOURCE="configured"
  log_info "Using configured bridge: ${BRIDGE}"
else
  BRIDGE="$(ip -o link show | awk -F': ' '/vmbr[0-9]+/ {
    iface=$2
    if (system("ip link show " iface " | grep -q \"state UP\"") == 0) {
      print iface
      exit
    }
  }' || true)"

  if [[ -z "${BRIDGE}" ]]; then
    log_warn "No active vmbr* bridge discovered; using fallback ${FALLBACK_BRIDGE}"
    BRIDGE="${FALLBACK_BRIDGE}"
    BRIDGE_SOURCE="configured"
  else
    log_info "Discovered active bridge: ${BRIDGE}"
  fi
fi

storage_supports() {
  local sid="$1"
  local content="$2"
  pvesh get "/storage/${sid}" --output-format json 2>/dev/null | grep -q "\"content\".*${content}"
}

require_storage() {
  local sid="$1"
  local content="$2"
  local label="$3"
  if [[ -z "${sid}" ]]; then
    log_error "${label} storage is empty"
    exit 1
  fi
  if ! pvesh get "/storage/${sid}" --output-format json >/dev/null 2>&1; then
    log_error "${label} storage '${sid}' does not exist"
    exit 1
  fi
  if ! storage_supports "${sid}" "${content}"; then
    log_error "${label} storage '${sid}' does not support '${content}' content"
    exit 1
  fi
}

require_bridge() {
  local bridge="$1"
  if [[ -z "${bridge}" ]]; then
    log_error "bridge is empty"
    exit 1
  fi
  if ! ip link show "${bridge}" >/dev/null 2>&1; then
    log_error "bridge '${bridge}' does not exist"
    exit 1
  fi
  if ! ip link show "${bridge}" | grep -q "state UP"; then
    log_error "bridge '${bridge}' exists but is not UP"
    exit 1
  fi
}

require_storage "${STORAGE_VM}" "images" "VM"
require_storage "${STORAGE_ISO}" "iso" "ISO"
require_storage "${STORAGE_SNIPPETS}" "snippets" "snippets"
require_bridge "${BRIDGE}"

log_info "Node=${NODE}"
log_info "IP=${IP}"
log_info "Storage VM=${STORAGE_VM}"
log_info "Storage ISO=${STORAGE_ISO}"
log_info "Storage snippets=${STORAGE_SNIPPETS}"
log_info "Bridge=${BRIDGE}"

USER_CREATED=0
TOKEN_CREATED=0

cleanup_partial_credentials() {
  local rc=$?
  if [[ "${rc}" -eq 0 ]]; then
    return
  fi
  set +e
  if [[ "${TOKEN_CREATED}" -eq 1 ]]; then
    if ! pveum user token remove "${USER_FQ}" "${TOKEN_NAME}" >/dev/null 2>&1; then
      log_error "Failed to remove token ${TOKEN_ID} during rollback"
    fi
  fi
  if [[ "${USER_CREATED}" -eq 1 ]]; then
    if ! pveum user delete "${USER_FQ}" >/dev/null 2>&1; then
      log_error "Failed to remove user ${USER_FQ} during rollback"
    fi
  fi
}
trap cleanup_partial_credentials EXIT

log_info "Provisioning API user: ${USER_FQ}"
if pveum user list --output-format json 2>/dev/null | grep -q "\"userid\":\"${USER_FQ}\""; then
  log_info "User exists"
else
  pveum user add "${USER_FQ}" --comment "HybridOps automation" 2>/dev/null || {
    log_error "Failed to create user"
    exit 1
  }
  USER_CREATED=1
  log_info "User created"
fi

log_info "Ensuring token: ${TOKEN_NAME}"
TOKEN_SECRET=""
TOKEN_EXISTS=0
if pveum user token list "${USER_FQ}" --output-format json 2>/dev/null | grep -q "\"tokenid\":\"${TOKEN_NAME}\""; then
  TOKEN_EXISTS=1
fi

if [[ -n "${SKIP_TOKEN_GEN:-}" ]]; then
  if [[ "${TOKEN_EXISTS}" -ne 1 ]]; then
    log_error "Token ${TOKEN_ID} does not exist for the stored vault secret"
    exit 1
  fi
  log_info "SKIP_TOKEN_GEN set; reusing existing vault secret"
else
  if [[ "${TOKEN_EXISTS}" -eq 1 ]]; then
    if [[ "${ALLOW_TOKEN_ROTATION:-}" != "1" ]]; then
      log_error "Token ${TOKEN_ID} already exists and rotation was not authorised"
      log_error "Choose a different token name or re-run with explicit --force authority"
      exit 3
    fi
    log_info "Rotating token"
    pveum user token remove "${USER_FQ}" "${TOKEN_NAME}" 2>/dev/null || true
  fi

  TOKEN_JSON="$(pveum user token add "${USER_FQ}" "${TOKEN_NAME}" --privsep=0 --expire=0 --output-format=json 2>/dev/null)" || {
    log_error "Token generation failed"
    exit 1
  }
  TOKEN_CREATED=1
  TOKEN_SECRET="$(printf '%s\n' "${TOKEN_JSON}" | sed -n 's/.*"value"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p')"

  if [[ -z "${TOKEN_SECRET}" ]]; then
    log_error "Token generation failed (empty secret)"
    exit 1
  fi
fi

require_acl() {
  local description="$1"
  shift
  if ! pveum acl modify "$@" 2>/dev/null; then
    log_error "Failed to set ACL on ${description}"
    exit 1
  fi
}

grant_storage_acls() {
  local subject_flag="$1"
  local subject="$2"
  local sid
  local -A seen=()
  for sid in "${STORAGE_VM}" "${STORAGE_ISO}" "${STORAGE_SNIPPETS}"; do
    if [[ -n "${seen[${sid}]:-}" ]]; then
      continue
    fi
    seen["${sid}"]=1
    require_acl "storage ${sid}" "/storage/${sid}" "${subject_flag}" "${subject}" --role PVEAdmin
  done
}

require_acl "/vms" /vms --user "${USER_FQ}" --role PVEVMAdmin
require_acl "bridge ${BRIDGE}" "/sdn/zones/localnetwork/${BRIDGE}" --user "${USER_FQ}" --role PVESDNUser
grant_storage_acls --user "${USER_FQ}"

require_acl "/" / --token "${TOKEN_ID}" --role PVEVMAdmin
require_acl "bridge ${BRIDGE}" "/sdn/zones/localnetwork/${BRIDGE}" --token "${TOKEN_ID}" --role PVESDNUser
grant_storage_acls --token "${TOKEN_ID}"

if [[ -n "${TOKEN_SECRET}" ]]; then
  printf 'EXPORT:TOKEN_SECRET=%s\n' "${TOKEN_SECRET}"
fi
printf 'EXPORT:NODE=%s\n' "${NODE}"
printf 'EXPORT:IP=%s\n' "${IP}"
printf 'EXPORT:STORAGE_VM=%s\n' "${STORAGE_VM}"
printf 'EXPORT:STORAGE_ISO=%s\n' "${STORAGE_ISO}"
printf 'EXPORT:STORAGE_SNIPPETS=%s\n' "${STORAGE_SNIPPETS}"
printf 'EXPORT:STORAGE_VM_SOURCE=%s\n' "${STORAGE_VM_SOURCE}"
printf 'EXPORT:STORAGE_ISO_SOURCE=%s\n' "${STORAGE_ISO_SOURCE}"
printf 'EXPORT:STORAGE_SNIPPETS_SOURCE=%s\n' "${STORAGE_SNIPPETS_SOURCE}"
printf 'EXPORT:BRIDGE=%s\n' "${BRIDGE}"
printf 'EXPORT:BRIDGE_SOURCE=%s\n' "${BRIDGE_SOURCE}"
printf 'EXPORT:USER_CREATED=%s\n' "${USER_CREATED}"
printf 'EXPORT:TOKEN_CREATED=%s\n' "${TOKEN_CREATED}"
