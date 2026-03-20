#!/usr/bin/env bash
# purpose: Install Ansible Galaxy dependencies into HybridOps runtime state.
# Architecture Decision: ADR-N/A
# maintainer: HybridOps.Tech

set -euo pipefail
umask 077

usage() {
  cat <<'USAGE'
Usage:
  setup-ansible.sh [--root <path>] [--requirements <path>] [--hybridops-source <release|git>]
                   [--hybridops-git-manifest <path>] [--force]

Options:
  --root <path>         HybridOps runtime root (default: ~/.hybridops or $HYOPS_RUNTIME_ROOT)
  --requirements <path> Galaxy requirements file for the shared/common dependency set
                        (default: tools/setup/requirements/ansible.galaxy.yml)
                        If relative, it is resolved relative to this script's release root.
  --hybridops-source <release|git>
                        How to source HybridOps collections for shared installs.
                        release  = install pinned released collections from Ansible Galaxy
                        git      = build/install pinned collections from Git repos into runtime state
                        (default: release or $HYOPS_SETUP_ANSIBLE_HYBRIDOPS_SOURCE)
  --hybridops-git-manifest <path>
                        Pinned Git collection manifest used when --hybridops-source git
                        (default: tools/setup/requirements/ansible.hybridops.git.json)
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
HYBRIDOPS_SOURCE="${HYOPS_SETUP_ANSIBLE_HYBRIDOPS_SOURCE:-release}"
HYBRIDOPS_GIT_MANIFEST_PATH="${HYOPS_SETUP_ANSIBLE_HYBRIDOPS_GIT_MANIFEST:-}"
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
    --hybridops-source)
      [[ $# -ge 2 && -n "${2:-}" && "${2:-}" != --* ]] || { echo "ERR: --hybridops-source requires a value" >&2; usage; exit 2; }
      HYBRIDOPS_SOURCE="${2}"
      shift 2
      ;;
    --hybridops-git-manifest)
      [[ $# -ge 2 && -n "${2:-}" && "${2:-}" != --* ]] || { echo "ERR: --hybridops-git-manifest requires a value" >&2; usage; exit 2; }
      HYBRIDOPS_GIT_MANIFEST_PATH="${2}"
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

case "${HYBRIDOPS_SOURCE}" in
  release|git)
    ;;
  *)
    echo "ERR: unsupported --hybridops-source: ${HYBRIDOPS_SOURCE} (expected release or git)" >&2
    exit 2
    ;;
esac

RUNTIME_ROOT="$(python3 - <<PY
from pathlib import Path
print(str(Path("${RUNTIME_ROOT}").expanduser().resolve()))
PY
)"

DEFAULT_REQ_REL="tools/setup/requirements/ansible.galaxy.yml"
DEFAULT_HYBRIDOPS_GIT_MANIFEST_REL="tools/setup/requirements/ansible.hybridops.git.json"
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

HYBRIDOPS_GIT_MANIFEST_FILE=""
if [[ "${HYBRIDOPS_SOURCE}" == "git" ]]; then
  need_cmd git
  if [[ -z "${HYBRIDOPS_GIT_MANIFEST_PATH}" ]]; then
    HYBRIDOPS_GIT_MANIFEST_FILE="${RELEASE_ROOT}/${DEFAULT_HYBRIDOPS_GIT_MANIFEST_REL}"
  else
    if [[ "${HYBRIDOPS_GIT_MANIFEST_PATH}" = /* ]]; then
      HYBRIDOPS_GIT_MANIFEST_FILE="${HYBRIDOPS_GIT_MANIFEST_PATH}"
    else
      HYBRIDOPS_GIT_MANIFEST_FILE="${RELEASE_ROOT}/${HYBRIDOPS_GIT_MANIFEST_PATH}"
    fi
  fi
  [[ -f "${HYBRIDOPS_GIT_MANIFEST_FILE}" ]] || {
    echo "ERR: missing HybridOps Git manifest: ${HYBRIDOPS_GIT_MANIFEST_FILE}" >&2
    exit 2
  }
fi

# temp/cache: keep ansible-galaxy reliable in constrained environments
TMP_DIR="${RUNTIME_ROOT}/tmp"
mkdir -p "${TMP_DIR}/ansible-local"
export TMPDIR="${TMP_DIR}"
export ANSIBLE_LOCAL_TEMP="${TMP_DIR}/ansible-local"
export ANSIBLE_REMOTE_TEMP="/tmp/.ansible-tmp"
export HYOPS_SETUP_ANSIBLE_HYBRIDOPS_SOURCE="${HYBRIDOPS_SOURCE}"
if [[ -n "${HYBRIDOPS_GIT_MANIFEST_FILE}" ]]; then
  export HYOPS_SETUP_ANSIBLE_HYBRIDOPS_GIT_MANIFEST="${HYBRIDOPS_GIT_MANIFEST_FILE}"
else
  unset HYOPS_SETUP_ANSIBLE_HYBRIDOPS_GIT_MANIFEST || true
fi

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

combine_hashes() {
  python3 - "$@" <<'PY'
import hashlib
import sys

h = hashlib.sha256()
for item in sys.argv[1:]:
    h.update(item.encode("utf-8"))
    h.update(b"\0")
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

hy_source = os.environ.get("HYOPS_SETUP_ANSIBLE_HYBRIDOPS_SOURCE", "").strip()
hy_manifest = os.environ.get("HYOPS_SETUP_ANSIBLE_HYBRIDOPS_GIT_MANIFEST", "").strip()
if scope == "common" and hy_source:
  payload["hybridops_source"] = hy_source
if scope == "common" and hy_manifest:
  payload["hybridops_git_manifest"] = hy_manifest

os.makedirs(os.path.dirname(marker_file), exist_ok=True)
with open(marker_file, "w", encoding="utf-8") as f:
  json.dump(payload, f, indent=2, sort_keys=True)
PY
}

install_hybridops_git_collections() {
  local manifest_file="$1"
  local collections_dir="$2"

  python3 - "$manifest_file" "$TMP_DIR" "$collections_dir" <<'PY'
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import json

manifest_path = Path(sys.argv[1]).resolve()
tmp_root = Path(sys.argv[2]).resolve()
collections_dir = Path(sys.argv[3]).resolve()

data = json.loads(manifest_path.read_text(encoding="utf-8"))
entries = data.get("collections") or []
if not isinstance(entries, list) or not entries:
    raise SystemExit(f"ERR: no collections defined in manifest: {manifest_path}")

work_root = tmp_root / "hybridops-collections-git"
shutil.rmtree(work_root, ignore_errors=True)
work_root.mkdir(parents=True, exist_ok=True)

env = os.environ.copy()

for entry in entries:
    if not isinstance(entry, dict):
        raise SystemExit(f"ERR: invalid collection entry in {manifest_path}: {entry!r}")
    fqcn = str(entry.get("name") or "").strip()
    repo = str(entry.get("repo") or "").strip()
    ref = str(entry.get("ref") or "").strip()
    if not fqcn or not repo or not ref:
        raise SystemExit(
            f"ERR: manifest entry must define name, repo, and ref: {entry!r}"
        )

    slug = fqcn.replace(".", "-")
    repo_dir = work_root / slug
    build_dir = work_root / f"{slug}-build"

    subprocess.run(["git", "clone", repo, str(repo_dir)], check=True, env=env)
    subprocess.run(["git", "checkout", ref], cwd=repo_dir, check=True, env=env)
    build_dir.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        ["ansible-galaxy", "collection", "build", "-v", "--output-path", str(build_dir)],
        cwd=repo_dir,
        check=True,
        env=env,
    )

    tarballs = sorted(build_dir.glob("*.tar.gz"))
    if not tarballs:
        raise SystemExit(f"ERR: no collection artifact built for {fqcn} from {repo}@{ref}")
    artifact = tarballs[-1]
    subprocess.run(
        [
            "ansible-galaxy",
            "collection",
            "install",
            str(artifact),
            "-p",
            str(collections_dir),
            "--force",
        ],
        check=True,
        env=env,
    )
    print(f"[setup] hybridops collection installed from git: {fqcn}@{ref}")
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
  if [[ "${scope}" == "common" && "${HYBRIDOPS_SOURCE}" == "git" ]]; then
    manifest_sha="$(sha256_file "${HYBRIDOPS_GIT_MANIFEST_FILE}")"
    req_sha="$(combine_hashes "${req_sha}" "${manifest_sha}" "${HYBRIDOPS_SOURCE}")"
  fi

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

  if [[ "${scope}" == "common" && "${HYBRIDOPS_SOURCE}" == "git" ]]; then
    ANSIBLE_COLLECTIONS_PATH="${collections_dir}:${collections_tail}" \
    ANSIBLE_ROLES_PATH="${roles_dir}:${roles_tail}" \
    install_hybridops_git_collections "${HYBRIDOPS_GIT_MANIFEST_FILE}" "${collections_dir}"
  fi

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

echo "[setup] ansible deps ready"
