#!/usr/bin/env bash
# purpose: Install Ansible Galaxy dependencies into HybridOps runtime state.
# Architecture Decision: ADR-N/A
# maintainer: HybridOps.Studio

set -euo pipefail
umask 077

usage() {
  cat <<'USAGE'
Usage:
  setup-ansible.sh [--root <path>] [--requirements <path>] [--force]

Options:
  --root <path>         HybridOps runtime root (default: ~/.hybridops or $HYOPS_RUNTIME_ROOT)
  --requirements <path> Galaxy requirements file for the shared/common dependency set
                        (default: tools/setup/requirements/ansible.galaxy.yml)
                        If relative, it is resolved relative to this script's release root.
  --force               Reinstall even if requirements hash is unchanged
  -h, --help            Show help
USAGE
}

need_cmd() { command -v "$1" >/dev/null 2>&1 || { echo "ERR: missing command: $1" >&2; exit 2; }; }

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
RELEASE_ROOT="$(cd -- "${SCRIPT_DIR}/../.." && pwd)"

RUNTIME_ROOT="${HYOPS_RUNTIME_ROOT:-$HOME/.hybridops}"
REQ_PATH=""
FORCE="false"

while [[ $# -gt 0 ]]; do
  case "${1:-}" in
    --root)
      [[ $# -ge 2 && -n "${2:-}" && "${2:-}" != --* ]] || { echo "ERR: --root requires a value" >&2; usage; exit 2; }
      RUNTIME_ROOT="${2}"
      shift 2
      ;;
    --requirements)
      [[ $# -ge 2 && -n "${2:-}" && "${2:-}" != --* ]] || { echo "ERR: --requirements requires a value" >&2; usage; exit 2; }
      REQ_PATH="${2}"
      shift 2
      ;;
    --force)
      FORCE="true"
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "ERR: unknown option: ${1}" >&2
      usage
      exit 2
      ;;
  esac
done

need_cmd python3
need_cmd ansible-galaxy

RUNTIME_ROOT="$(python3 - <<PY
from pathlib import Path
print(str(Path("${RUNTIME_ROOT}").expanduser().resolve()))
PY
)"

DEFAULT_REQ_REL="tools/setup/requirements/ansible.galaxy.yml"
if [[ -z "${REQ_PATH}" ]]; then
  REQ_FILE="${RELEASE_ROOT}/${DEFAULT_REQ_REL}"
else
  if [[ "${REQ_PATH}" = /* ]]; then
    REQ_FILE="${REQ_PATH}"
  else
    REQ_FILE="${RELEASE_ROOT}/${REQ_PATH}"
  fi
fi

[[ -f "${REQ_FILE}" ]] || { echo "ERR: missing requirements file: ${REQ_FILE}" >&2; exit 2; }

# temp/cache: keep ansible-galaxy reliable in constrained environments
TMP_DIR="${RUNTIME_ROOT}/tmp"
mkdir -p "${TMP_DIR}/ansible-local"
export TMPDIR="${TMP_DIR}"
export ANSIBLE_LOCAL_TEMP="${TMP_DIR}/ansible-local"
export ANSIBLE_REMOTE_TEMP="/tmp/.ansible-tmp"

sha256_file() {
  python3 - "$1" <<'PY'
import hashlib, sys
p = sys.argv[1]
h = hashlib.sha256()
with open(p, "rb") as f:
    for chunk in iter(lambda: f.read(65536), b""):
        h.update(chunk)
print(h.hexdigest())
PY
}

marker_matches() {
  python3 - "$1" "$2" <<'PY' >/dev/null 2>&1
import json, sys
from pathlib import Path
marker, sha = sys.argv[1], sys.argv[2]
try:
    d = json.loads(Path(marker).read_text(encoding="utf-8"))
    raise SystemExit(0 if d.get("requirements_sha256") == sha else 1)
except Exception:
    raise SystemExit(1)
PY
}

write_marker() {
  local marker_file="$1"
  local req_file="$2"
  local req_sha="$3"
  local collections_dir="$4"
  local roles_dir="$5"
  local scope="$6"
  local module_ref="${7:-}"

  python3 - "$marker_file" "$req_file" "$req_sha" "$collections_dir" "$roles_dir" "$scope" "$module_ref" <<'PY'
import json, os, sys, time
from pathlib import Path

marker_file, req_file, req_sha, collections_dir, roles_dir, scope, module_ref = sys.argv[1:8]
release_root = Path(os.environ.get("HYOPS_RELEASE_ROOT") or ".").resolve()
req_file_path = Path(req_file).resolve()

try:
    requirements_rel = str(req_file_path.relative_to(release_root))
except Exception:
    requirements_rel = ""

payload = {
  "timestamp_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
  "release_root": str(release_root),
  "requirements_file": str(req_file_path),
  "requirements_rel": requirements_rel,
  "requirements_sha256": req_sha,
  "collections_dir": collections_dir,
  "roles_dir": roles_dir,
  "scope": scope,
}
if module_ref:
  payload["module_ref"] = module_ref

os.makedirs(os.path.dirname(marker_file), exist_ok=True)
with open(marker_file, "w", encoding="utf-8") as f:
  json.dump(payload, f, indent=2, sort_keys=True)
PY
}

install_set() {
  local name="$1"
  local scope="$2"          # common | module
  local module_ref="${3:-}" # only used when scope=module
  local req_file="$4"
  local state_dir="$5"

  [[ -f "${req_file}" ]] || { echo "ERR: missing requirements file: ${req_file}" >&2; exit 2; }

  local collections_dir roles_dir marker_file req_sha
  # Avoid ansible-galaxy warning about paths containing ".../ansible/collections".
  collections_dir="${state_dir}/galaxy_collections"
  roles_dir="${state_dir}/roles"
  marker_file="${state_dir}/.installed.json"

  mkdir -p "${collections_dir}" "${roles_dir}"

  req_sha="$(sha256_file "${req_file}")"

  if [[ "${FORCE}" != "true" && -f "${marker_file}" ]]; then
    if marker_matches "${marker_file}" "${req_sha}"; then
      echo "[setup] ansible deps already satisfied: ${name}"
      return 0
    fi
  fi

  local collections_tail roles_tail
  collections_tail="${ANSIBLE_COLLECTIONS_PATH:-${ANSIBLE_COLLECTIONS_PATHS:-$HOME/.ansible/collections:/usr/share/ansible/collections}}"
  roles_tail="${ANSIBLE_ROLES_PATH:-$HOME/.ansible/roles:/etc/ansible/roles}"

  env -u ANSIBLE_COLLECTIONS_PATHS \
    ANSIBLE_COLLECTIONS_PATH="${collections_dir}:${collections_tail}" \
    ANSIBLE_ROLES_PATH="${roles_dir}:${roles_tail}" \
    ansible-galaxy collection install -r "${req_file}" -p "${collections_dir}" --force

  env -u ANSIBLE_COLLECTIONS_PATHS \
    ANSIBLE_COLLECTIONS_PATH="${collections_dir}:${collections_tail}" \
    ANSIBLE_ROLES_PATH="${roles_dir}:${roles_tail}" \
    ansible-galaxy role install -r "${req_file}" -p "${roles_dir}" --force >/dev/null 2>&1 || true

  write_marker "${marker_file}" "${req_file}" "${req_sha}" "${collections_dir}" "${roles_dir}" "${scope}" "${module_ref}"
  echo "[setup] ansible deps installed: ${name}"
}

export HYOPS_RELEASE_ROOT="${RELEASE_ROOT}"

# Shared/common set (compatible across most workflows)
install_set "common" "common" "" "${REQ_FILE}" "${RUNTIME_ROOT}/state/ansible"

# Module-specific sets are installed into isolated paths to avoid Galaxy dependency conflicts.
# These paths are added automatically at runtime by the Ansible driver when the module runs.
install_set "platform/postgresql-ha" "module" "platform/postgresql-ha" \
  "${RELEASE_ROOT}/tools/setup/requirements/ansible.postgresql-ha.galaxy.yml" \
  "${RUNTIME_ROOT}/state/ansible/modules/platform__postgresql-ha"

install_set "platform/onprem/postgresql-ha (legacy alias)" "module" "platform/onprem/postgresql-ha" \
  "${RELEASE_ROOT}/tools/setup/requirements/ansible.postgresql-ha.galaxy.yml" \
  "${RUNTIME_ROOT}/state/ansible/modules/platform__onprem__postgresql-ha"

install_set "platform/postgresql-ha-backup" "module" "platform/postgresql-ha-backup" \
  "${RELEASE_ROOT}/tools/setup/requirements/ansible.postgresql-ha.galaxy.yml" \
  "${RUNTIME_ROOT}/state/ansible/modules/platform__postgresql-ha-backup"

install_set "platform/onprem/postgresql-ha-backup (legacy alias)" "module" "platform/onprem/postgresql-ha-backup" \
  "${RELEASE_ROOT}/tools/setup/requirements/ansible.postgresql-ha.galaxy.yml" \
  "${RUNTIME_ROOT}/state/ansible/modules/platform__onprem__postgresql-ha-backup"

install_set "platform/onprem/rke2-cluster" "module" "platform/onprem/rke2-cluster" \
  "${RELEASE_ROOT}/tools/setup/requirements/ansible.rke2-cluster.galaxy.yml" \
  "${RUNTIME_ROOT}/state/ansible/modules/platform__onprem__rke2-cluster"

install_set "platform/network/wan-edge" "module" "platform/network/wan-edge" \
  "${RELEASE_ROOT}/tools/setup/requirements/ansible.wan-edge.galaxy.yml" \
  "${RUNTIME_ROOT}/state/ansible/modules/platform__network__wan-edge"

echo "[setup] ansible deps ready"
