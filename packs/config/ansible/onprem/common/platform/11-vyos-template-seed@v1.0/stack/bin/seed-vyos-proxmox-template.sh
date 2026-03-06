#!/usr/bin/env bash
set -euo pipefail

require() {
  local name="$1"
  if [[ -z "${!name:-}" ]]; then
    echo "missing required env: ${name}" >&2
    exit 2
  fi
}

require PROXMOX_HOST
require PROXMOX_SSH_USER
require PROXMOX_SSH_KEY
require TEMPLATE_VMID
require TEMPLATE_NAME
require IMAGE_SOURCE_URL
require STORAGE_VM
require NETWORK_BRIDGE
require CPU_CORES
require MEMORY_MB
require CI_USERNAME

SSH_OPTS=(
  -o BatchMode=yes
  -o StrictHostKeyChecking=no
  -o UserKnownHostsFile=/dev/null
  -o LogLevel=ERROR
  -i "${PROXMOX_SSH_KEY}"
)

REMOTE="${PROXMOX_SSH_USER}@${PROXMOX_HOST}"
REMOTE_TMP="/var/tmp/hyops-vyos-template-${TEMPLATE_VMID}"
REBUILD_IF_EXISTS="${REBUILD_IF_EXISTS:-false}"
TEMPLATE_SMOKE_GATE="${TEMPLATE_SMOKE_GATE:-true}"
TEMPLATE_SMOKE_WAIT_S="${TEMPLATE_SMOKE_WAIT_S:-90}"
TEMPLATE_SMOKE_VMID="${TEMPLATE_SMOKE_VMID:-$((TEMPLATE_VMID + 9000))}"
TEMPLATE_SMOKE_BRIDGE="${TEMPLATE_SMOKE_BRIDGE:-${NETWORK_BRIDGE}}"
TEMPLATE_SMOKE_MARKER="${TEMPLATE_SMOKE_MARKER:-hyops-template-smoke-${TEMPLATE_VMID}}"
LOCAL_TMP="$(mktemp -d)"
LOCAL_SOURCE="${LOCAL_TMP}/source"
LOCAL_DISK="${LOCAL_TMP}/disk"
gcs_sa_json_file="${HYOPS_VYOS_GCS_SA_JSON_FILE:-}"

cleanup_local() {
  rm -rf "${LOCAL_TMP}"
}
trap cleanup_local EXIT

ssh_run() {
  ssh "${SSH_OPTS[@]}" "${REMOTE}" "$@"
}

scp_to_remote() {
  scp "${SSH_OPTS[@]}" "$1" "${REMOTE}:$2"
}

require_cmd() {
  local name="$1"
  if ! command -v "$name" >/dev/null 2>&1; then
    echo "Required command missing: ${name}" >&2
    exit 5
  fi
}

base64url() {
  base64 | tr -d '\n=' | tr '+/' '-_'
}

json_get() {
  local key="$1"
  local src_file="$2"
  python3 - "$key" "$src_file" <<'PY'
import json, sys
key = sys.argv[1]
path = sys.argv[2]
with open(path, "r", encoding="utf-8") as fh:
    data = json.load(fh)
value = data.get(key, "")
if not isinstance(value, str):
    value = str(value)
sys.stdout.write(value)
PY
}

urlencode() {
  python3 - "$1" <<'PY'
import sys
from urllib.parse import quote
sys.stdout.write(quote(sys.argv[1], safe=""))
PY
}

make_gcs_access_token() {
  local sa_file="$1"
  local client_email private_key token_uri now exp header claims signing_input jwt response access_token
  require_cmd openssl
  client_email="$(json_get client_email "$sa_file")"
  private_key="$(json_get private_key "$sa_file")"
  token_uri="$(json_get token_uri "$sa_file")"
  if [[ -z "$client_email" || -z "$private_key" ]]; then
    echo "Service account JSON is missing client_email/private_key" >&2
    exit 6
  fi
  if [[ -z "$token_uri" ]]; then
    token_uri="https://oauth2.googleapis.com/token"
  fi
  now="$(date +%s)"
  exp="$((now + 3600))"
  header='{"alg":"RS256","typ":"JWT"}'
  claims="$(python3 - "$client_email" "$token_uri" "$now" "$exp" <<'PY'
import json, sys
print(json.dumps({
    "iss": sys.argv[1],
    "scope": "https://www.googleapis.com/auth/devstorage.read_only",
    "aud": sys.argv[2],
    "iat": int(sys.argv[3]),
    "exp": int(sys.argv[4]),
}, separators=(",", ":")))
PY
)"
  signing_input="$(printf '%s' "$header" | base64url).$(printf '%s' "$claims" | base64url)"
  local key_file
  key_file="$(mktemp)"
  printf '%s\n' "$private_key" >"$key_file"
  jwt="${signing_input}.$(printf '%s' "$signing_input" | openssl dgst -sha256 -sign "$key_file" -binary | base64url)"
  rm -f "$key_file"
  response="$(curl -fsS -X POST "$token_uri" \
    -H 'Content-Type: application/x-www-form-urlencoded' \
    --data-urlencode 'grant_type=urn:ietf:params:oauth:grant-type:jwt-bearer' \
    --data-urlencode "assertion=$jwt")"
  access_token="$(python3 - "$response" <<'PY'
import json, sys
payload = json.loads(sys.argv[1])
token = payload.get("access_token", "")
if not token:
    raise SystemExit(payload.get("error_description") or payload.get("error") or "missing access_token")
sys.stdout.write(token)
PY
)"
  printf '%s' "$access_token"
}

download_gcs_via_api() {
  local bucket="$1"
  local object_name="$2"
  local output_file="$3"
  local sa_file="$4"
  local access_token download_url
  access_token="$(make_gcs_access_token "$sa_file")"
  download_url="https://storage.googleapis.com/storage/v1/b/${bucket}/o/$(urlencode "$object_name")?alt=media"
  curl -fsS "$download_url" \
    -H "Authorization: Bearer ${access_token}" \
    -o "$output_file"
}

download_source_artifact() {
  local url="$1"
  local output_file="$2"
  case "$url" in
    gs://*)
      local bucket_and_path bucket object_name
      bucket_and_path="${url#gs://}"
      bucket="${bucket_and_path%%/*}"
      object_name="${bucket_and_path#${bucket}/}"
      if [[ -n "$gcs_sa_json_file" && -f "$gcs_sa_json_file" ]]; then
        download_gcs_via_api "$bucket" "$object_name" "$output_file" "$gcs_sa_json_file"
      elif command -v gcloud >/dev/null 2>&1; then
        gcloud storage cp "$url" "$output_file"
      elif command -v gsutil >/dev/null 2>&1; then
        gsutil cp "$url" "$output_file"
      else
        echo "Private GCS source requires gcloud/gsutil or HYOPS_VYOS_GCS_SA_JSON_FILE" >&2
        exit 7
      fi
      ;;
    https://storage.googleapis.com/*)
      local bucket_and_path bucket object_name
      bucket_and_path="${url#https://storage.googleapis.com/}"
      bucket="${bucket_and_path%%/*}"
      object_name="${bucket_and_path#${bucket}/}"
      if [[ -n "$gcs_sa_json_file" && -f "$gcs_sa_json_file" ]]; then
        download_gcs_via_api "$bucket" "$object_name" "$output_file" "$gcs_sa_json_file"
      elif command -v gcloud >/dev/null 2>&1; then
        gcloud storage cp "gs://${bucket_and_path}" "$output_file"
      elif command -v gsutil >/dev/null 2>&1; then
        gsutil cp "gs://${bucket_and_path}" "$output_file"
      else
        echo "Private GCS source requires gcloud/gsutil or HYOPS_VYOS_GCS_SA_JSON_FILE" >&2
        exit 7
      fi
      ;;
    file://*)
      local_path="${url#file://}"
      if [[ ! -f "$local_path" ]]; then
        echo "Local source artifact not found: ${local_path}" >&2
        exit 8
      fi
      cp "$local_path" "$output_file"
      ;;
    /*)
      if [[ ! -f "$url" ]]; then
        echo "Local source artifact not found: ${url}" >&2
        exit 8
      fi
      cp "$url" "$output_file"
      ;;
    *)
      curl -fsSL "$url" -o "$output_file"
      ;;
  esac
}

if ssh_run "qm config '${TEMPLATE_VMID}'" >/tmp/hyops-vyos-template-config.$$ 2>/dev/null; then
  if grep -q '^template: 1$' "/tmp/hyops-vyos-template-config.$$"; then
    if [[ "${REBUILD_IF_EXISTS}" != "true" ]]; then
      echo "template_vm_id=${TEMPLATE_VMID}"
      rm -f "/tmp/hyops-vyos-template-config.$$"
      exit 0
    fi
  else
    if [[ "${REBUILD_IF_EXISTS}" != "true" ]]; then
      echo "vmid ${TEMPLATE_VMID} already exists but is not a template; set rebuild_if_exists=true or choose a different template_vm_id" >&2
      rm -f "/tmp/hyops-vyos-template-config.$$"
      exit 3
    fi
  fi
  rm -f "/tmp/hyops-vyos-template-config.$$"
  ssh_run "set -euo pipefail; qm stop '${TEMPLATE_VMID}' >/dev/null 2>&1 || true; qm destroy '${TEMPLATE_VMID}' --purge 1 --destroy-unreferenced-disks 1 >/dev/null 2>&1 || true"
fi

read -r -d '' REMOTE_PREP <<'EOF' || true
set -euo pipefail
rm -rf "${REMOTE_TMP}"
mkdir -p "${REMOTE_TMP}"
EOF

download_source_artifact "${IMAGE_SOURCE_URL}" "${LOCAL_SOURCE}"
REMOTE_SOURCE=0
REMOTE_BUCKET=""
REMOTE_OBJECT=""
if [[ ! -s "${LOCAL_SOURCE}" ]]; then
  case "${IMAGE_SOURCE_URL}" in
    gs://*|https://storage.googleapis.com/*)
      if [[ -n "$gcs_sa_json_file" && -f "$gcs_sa_json_file" ]]; then
        REMOTE_SOURCE=1
        if [[ "${IMAGE_SOURCE_URL}" == gs://* ]]; then
          bucket_and_path="${IMAGE_SOURCE_URL#gs://}"
        else
          bucket_and_path="${IMAGE_SOURCE_URL#https://storage.googleapis.com/}"
        fi
        REMOTE_BUCKET="${bucket_and_path%%/*}"
        REMOTE_OBJECT="${bucket_and_path#${REMOTE_BUCKET}/}"
      fi
      ;;
  esac
fi

if [[ "${REMOTE_SOURCE}" -eq 0 ]]; then
  if [[ ! -s "${LOCAL_SOURCE}" ]]; then
    echo "Downloaded source artifact is empty: ${LOCAL_SOURCE}" >&2
    exit 8
  fi
  case "${IMAGE_SOURCE_URL}" in
    *.xz) xz -dc "${LOCAL_SOURCE}" > "${LOCAL_DISK}" ;;
    *.gz) gzip -dc "${LOCAL_SOURCE}" > "${LOCAL_DISK}" ;;
    *) cp "${LOCAL_SOURCE}" "${LOCAL_DISK}" ;;
  esac
fi

ssh_run "REMOTE_TMP='${REMOTE_TMP}' bash -lc $(printf '%q' "${REMOTE_PREP}")"
if [[ "${REMOTE_SOURCE}" -eq 0 ]]; then
  scp_to_remote "${LOCAL_DISK}" "${REMOTE_TMP}/disk"
fi

read -r -d '' REMOTE_BUILD <<'EOF' || true
set -euo pipefail
if [[ "${REMOTE_SOURCE}" == "1" ]]; then
  case "${IMAGE_SOURCE_URL}" in
    *.xz) xz -dc "${REMOTE_TMP}/source" > "${REMOTE_TMP}/disk" ;;
    *.gz) gzip -dc "${REMOTE_TMP}/source" > "${REMOTE_TMP}/disk" ;;
    *) cp "${REMOTE_TMP}/source" "${REMOTE_TMP}/disk" ;;
  esac
fi
qm create "${TEMPLATE_VMID}" \
  --name "${TEMPLATE_NAME}" \
  --memory "${MEMORY_MB}" \
  --cores "${CPU_CORES}" \
  --ostype l26 \
  --bios seabios \
  --net0 "virtio,bridge=${NETWORK_BRIDGE}" \
  --serial0 socket \
  --vga serial0 \
  --agent enabled=0
qm importdisk "${TEMPLATE_VMID}" "${REMOTE_TMP}/disk" "${STORAGE_VM}"
UNUSED="$(qm config "${TEMPLATE_VMID}" | awk -F': ' '/^unused[0-9]+: /{print $2; exit}')"
UNUSED="${UNUSED%%,*}"
if [[ -z "${UNUSED}" ]]; then
  echo "unable to resolve imported disk reference for template ${TEMPLATE_VMID}" >&2
  exit 4
fi
qm set "${TEMPLATE_VMID}" --scsihw virtio-scsi-pci --scsi0 "${UNUSED}"
qm set "${TEMPLATE_VMID}" --ide2 "${STORAGE_VM}:cloudinit"
qm set "${TEMPLATE_VMID}" --boot order=scsi0
qm set "${TEMPLATE_VMID}" --ciuser "${CI_USERNAME}"

# Ensure the imported VyOS disk has cloud-init wired for vyos_config_commands.
SCSI0_REF="$(qm config "${TEMPLATE_VMID}" | awk -F': ' '/^scsi0: /{print $2; exit}')"
SCSI0_REF="${SCSI0_REF%%,*}"
if [[ -z "${SCSI0_REF}" || "${SCSI0_REF}" != *:* ]]; then
  echo "unable to resolve scsi0 disk for template ${TEMPLATE_VMID}" >&2
  exit 27
fi
LV_NAME="${SCSI0_REF#*:}"
LV_PATH="/dev/pve/${LV_NAME}"
if [[ ! -b "${LV_PATH}" ]]; then
  echo "expected LVM block device not found for template ${TEMPLATE_VMID}: ${LV_PATH}" >&2
  exit 28
fi
MAPPER_BASE="pve-${LV_NAME//-/--}"
ROOT_PART="/dev/mapper/${MAPPER_BASE}p3"
MNT="/var/tmp/hyops-vyos-template-mnt-${TEMPLATE_VMID}"
cleanup_template_mount() {
  set +e
  if mountpoint -q "${MNT}"; then
    umount "${MNT}" >/dev/null 2>&1 || true
  fi
  kpartx -d "${LV_PATH}" >/dev/null 2>&1 || true
  rmdir "${MNT}" >/dev/null 2>&1 || true
}
trap cleanup_template_mount EXIT
kpartx -a "${LV_PATH}" >/dev/null
if [[ ! -b "${ROOT_PART}" ]]; then
  echo "expected root partition mapper not found for template ${TEMPLATE_VMID}: ${ROOT_PART}" >&2
  exit 29
fi
mkdir -p "${MNT}"
mount "${ROOT_PART}" "${MNT}"
RW_ROOT="$(find "${MNT}/boot" -mindepth 2 -maxdepth 2 -type d -name rw | head -n1 || true)"
if [[ -z "${RW_ROOT}" ]]; then
  echo "unable to locate VyOS rw root under ${MNT}/boot for template ${TEMPLATE_VMID}" >&2
  exit 30
fi
CLOUD_CFG="${RW_ROOT}/etc/cloud/cloud.cfg"
CC_VYOS="${RW_ROOT}/usr/lib/python3/dist-packages/cloudinit/config/cc_vyos.py"
if [[ ! -f "${CC_VYOS}" ]]; then
  echo "missing ${CC_VYOS}; vyos cloud-init module is required for vyos_config_commands" >&2
  exit 31
fi
if [[ ! -f "${CLOUD_CFG}" ]]; then
  echo "missing ${CLOUD_CFG} on imported template disk" >&2
  exit 32
fi
python3 - "${CLOUD_CFG}" <<'PY'
from pathlib import Path
import sys

path = Path(sys.argv[1])
lines = path.read_text(encoding="utf-8").splitlines()

if any(line.strip() == "- vyos" for line in lines):
    raise SystemExit(0)

start = None
for idx, line in enumerate(lines):
    if line.strip() == "cloud_config_modules:":
        start = idx
        break

if start is None:
    lines.extend(["", "cloud_config_modules:", " - vyos"])
else:
    insert_at = start + 1
    while insert_at < len(lines):
        row = lines[insert_at]
        stripped = row.strip()
        if stripped == "" or row.startswith(" - ") or row.startswith("- "):
            insert_at += 1
            continue
        break
    lines.insert(insert_at, " - vyos")

path.write_text("\n".join(lines) + "\n", encoding="utf-8")
PY
python3 - "${CC_VYOS}" <<'PY'
from pathlib import Path
import re
import sys

path = Path(sys.argv[1])
text = path.read_text(encoding="utf-8")
source_patch = (
    "try:\n"
    "    from cloudinit.sources import INSTANCE_JSON_FILE\n"
    "except ImportError:\n"
    "    INSTANCE_JSON_FILE = 'instance-data.json'\n"
)
if source_patch not in text:
    needle = "from cloudinit.sources import INSTANCE_JSON_FILE\n"
    if needle in text:
        text = text.replace(needle, source_patch, 1)
    else:
        text = text.replace(
            "from cloudinit.settings import PER_INSTANCE\n",
            "from cloudinit.settings import PER_INSTANCE\n" + source_patch,
            1,
        )

if "from cloudinit.distros import ALL_DISTROS\n" not in text:
    text = text.replace(
        "from cloudinit.distros import ug_util\n",
        "from cloudinit.distros import ug_util\nfrom cloudinit.distros import ALL_DISTROS\n",
        1,
    )
if "from cloudinit.config.schema import MetaSchema, get_meta_doc\n" not in text:
    text = text.replace(
        "from cloudinit.settings import PER_INSTANCE\n",
        "from cloudinit.config.schema import MetaSchema, get_meta_doc\nfrom cloudinit.settings import PER_INSTANCE\n",
        1,
    )

meta_block = (
    "MODULE_DESCRIPTION = \"Apply VyOS-specific cloud-init configuration.\"\n"
    "MODULE_EXAMPLES = [\n"
    "    \"\"\"#cloud-config\\n"
    "vyos_config_commands:\\n"
    "  - set interfaces ethernet eth0 address 'dhcp'\\n"
    "\"\"\"\n"
    "]\n\n"
    "meta: MetaSchema = {\n"
    "    \"id\": \"cc_vyos\",\n"
    "    \"name\": \"VyOS\",\n"
    "    \"title\": \"Apply VyOS cloud-init configuration\",\n"
    "    \"description\": MODULE_DESCRIPTION,\n"
    "    \"examples\": MODULE_EXAMPLES,\n"
    "    \"distros\": [ALL_DISTROS],\n"
    "    \"frequency\": PER_INSTANCE,\n"
    "    \"activate_by_schema_keys\": [\"vyos_config_commands\"],\n"
    "}\n\n"
    "__doc__ = get_meta_doc(meta)\n\n"
)
if "meta: MetaSchema" not in text:
    text = text.replace("frequency = PER_INSTANCE\n\n", "frequency = PER_INSTANCE\n\n" + meta_block, 1)
else:
    if "MODULE_EXAMPLES" not in text:
        text = text.replace(
            "MODULE_DESCRIPTION = \"Apply VyOS-specific cloud-init configuration.\"\n",
            "MODULE_DESCRIPTION = \"Apply VyOS-specific cloud-init configuration.\"\n"
            "MODULE_EXAMPLES = [\n"
            "    \"\"\"#cloud-config\\n"
            "vyos_config_commands:\\n"
            "  - set interfaces ethernet eth0 address 'dhcp'\\n"
            "\"\"\"\n"
            "]\n",
            1,
        )
    meta_match = re.search(r"meta:\s*MetaSchema\s*=\s*\{.*?\n\}", text, re.S)
    if meta_match and "\"examples\"" not in meta_match.group(0):
        patched = meta_match.group(0)
        if "\"description\": MODULE_DESCRIPTION,\n" in patched:
            patched = patched.replace(
                "\"description\": MODULE_DESCRIPTION,\n",
                "\"description\": MODULE_DESCRIPTION,\n    \"examples\": MODULE_EXAMPLES,\n",
                1,
            )
        elif "\"distros\": [ALL_DISTROS],\n" in patched:
            patched = patched.replace(
                "\"distros\": [ALL_DISTROS],\n",
                "\"examples\": MODULE_EXAMPLES,\n    \"distros\": [ALL_DISTROS],\n",
                1,
            )
        text = text[:meta_match.start()] + patched + text[meta_match.end():]

legacy_hostname_unpack = "(hostname, fqdn) = get_hostname_fqdn(cfg, cloud, metadata_only=True)\n"
modern_hostname_unpack = (
    "hostname_info = get_hostname_fqdn(cfg, cloud, metadata_only=True)\n"
    "    hostname = getattr(hostname_info, 'hostname', None)\n"
    "    fqdn = getattr(hostname_info, 'fqdn', None)\n"
    "    if hostname is None and isinstance(hostname_info, (tuple, list)) and len(hostname_info) >= 2:\n"
    "        hostname, fqdn = hostname_info[0], hostname_info[1]\n"
)
if legacy_hostname_unpack in text and modern_hostname_unpack not in text:
    text = text.replace(legacy_hostname_unpack, modern_hostname_unpack, 1)

path.write_text(text, encoding="utf-8")
PY
rm -rf "${RW_ROOT}/var/lib/cloud/instances" "${RW_ROOT}/var/lib/cloud/instance" "${RW_ROOT}/var/lib/cloud/sem" || true
cleanup_template_mount
trap - EXIT

qm template "${TEMPLATE_VMID}"
rm -rf "${REMOTE_TMP}"
EOF

if [[ "${REMOTE_SOURCE}" -eq 1 ]]; then
  access_token="$(make_gcs_access_token "$gcs_sa_json_file")"
  remote_url="https://storage.googleapis.com/storage/v1/b/${REMOTE_BUCKET}/o/$(urlencode "$REMOTE_OBJECT")?alt=media"
  ssh_run "REMOTE_TMP='${REMOTE_TMP}' curl -fsS -H 'Authorization: Bearer ${access_token}' -o '${REMOTE_TMP}/source' '${remote_url}'"
fi

ssh_run \
  "REMOTE_TMP='${REMOTE_TMP}' TEMPLATE_VMID='${TEMPLATE_VMID}' TEMPLATE_NAME='${TEMPLATE_NAME}' STORAGE_VM='${STORAGE_VM}' NETWORK_BRIDGE='${NETWORK_BRIDGE}' CPU_CORES='${CPU_CORES}' MEMORY_MB='${MEMORY_MB}' CI_USERNAME='${CI_USERNAME}' IMAGE_SOURCE_URL='${IMAGE_SOURCE_URL}' REMOTE_SOURCE='${REMOTE_SOURCE}' bash -lc $(printf '%q' "${REMOTE_BUILD}")"

if [[ "${TEMPLATE_SMOKE_GATE,,}" == "1" || "${TEMPLATE_SMOKE_GATE,,}" == "true" || "${TEMPLATE_SMOKE_GATE,,}" == "yes" || "${TEMPLATE_SMOKE_GATE,,}" == "on" ]]; then
  read -r -d '' REMOTE_SMOKE <<'EOF' || true
set -euo pipefail

SMOKE_VMID="${TEMPLATE_SMOKE_VMID}"
SMOKE_NAME="smoke-${SMOKE_VMID}"
SMOKE_BRIDGE="${TEMPLATE_SMOKE_BRIDGE}"
SMOKE_WAIT_S="${TEMPLATE_SMOKE_WAIT_S}"
SMOKE_MARKER="${TEMPLATE_SMOKE_MARKER}"

SMOKE_USER_SNIPPET="hyops-vyos-smoke-${SMOKE_VMID}-user.yaml"
SMOKE_META_SNIPPET="hyops-vyos-smoke-${SMOKE_VMID}-meta.yaml"
SMOKE_USER_PATH="/var/lib/vz/snippets/${SMOKE_USER_SNIPPET}"
SMOKE_META_PATH="/var/lib/vz/snippets/${SMOKE_META_SNIPPET}"
SMOKE_MNT="/var/tmp/hyops-vyos-smoke-mnt-${SMOKE_VMID}"
SMOKE_LV=""
SMOKE_PART=""

cleanup_smoke() {
  set +e
  if mountpoint -q "${SMOKE_MNT}"; then
    umount "${SMOKE_MNT}" >/dev/null 2>&1 || true
  fi
  if [[ -n "${SMOKE_LV}" ]]; then
    kpartx -d "${SMOKE_LV}" >/dev/null 2>&1 || true
  fi
  qm stop "${SMOKE_VMID}" >/dev/null 2>&1 || true
  qm destroy "${SMOKE_VMID}" --purge 1 --destroy-unreferenced-disks 1 >/dev/null 2>&1 || true
  for stale_lv in /dev/pve/vm-"${SMOKE_VMID}"-cloudinit /dev/pve/vm-"${SMOKE_VMID}"-disk-*; do
    if [[ -b "${stale_lv}" ]]; then
      lvremove -fy "${stale_lv}" >/dev/null 2>&1 || true
    fi
  done
  rm -f "${SMOKE_USER_PATH}" "${SMOKE_META_PATH}" >/dev/null 2>&1 || true
  rmdir "${SMOKE_MNT}" >/dev/null 2>&1 || true
}
trap cleanup_smoke EXIT

qm stop "${SMOKE_VMID}" >/dev/null 2>&1 || true
qm destroy "${SMOKE_VMID}" --purge 1 --destroy-unreferenced-disks 1 >/dev/null 2>&1 || true
for stale_lv in /dev/pve/vm-"${SMOKE_VMID}"-cloudinit /dev/pve/vm-"${SMOKE_VMID}"-disk-*; do
  if [[ -b "${stale_lv}" ]]; then
    lvremove -fy "${stale_lv}" >/dev/null 2>&1 || true
  fi
done

cat > "${SMOKE_USER_PATH}" <<USERDATA
#cloud-config
hostname: ${SMOKE_MARKER}
manage_etc_hosts: true
network:
  config: disabled
vyos_config_commands:
  - "set interfaces ethernet eth0 address 'dhcp'"
  - "set service ssh port '22'"
USERDATA

cat > "${SMOKE_META_PATH}" <<METADATA
instance-id: ${SMOKE_MARKER}
local-hostname: ${SMOKE_MARKER}
METADATA

qm clone "${TEMPLATE_VMID}" "${SMOKE_VMID}" --name "${SMOKE_NAME}" --full 1
qm set "${SMOKE_VMID}" --net0 "virtio,bridge=${SMOKE_BRIDGE}"
if ! qm config "${SMOKE_VMID}" | grep -qE '^ide2: .*cloudinit'; then
  qm set "${SMOKE_VMID}" --ide2 "${STORAGE_VM}:cloudinit"
fi
qm set "${SMOKE_VMID}" --ciuser "${CI_USERNAME}"
qm set "${SMOKE_VMID}" --cicustom "user=local:snippets/${SMOKE_USER_SNIPPET},meta=local:snippets/${SMOKE_META_SNIPPET}"
qm set "${SMOKE_VMID}" --boot order=scsi0
qm start "${SMOKE_VMID}"
sleep "${SMOKE_WAIT_S}"
qm stop "${SMOKE_VMID}" >/dev/null 2>&1 || true

DISK_REF="$(qm config "${SMOKE_VMID}" | awk -F': ' '/^scsi0: /{print $2; exit}')"
DISK_REF="${DISK_REF%%,*}"
if [[ -z "${DISK_REF}" || "${DISK_REF}" != *:* ]]; then
  echo "smoke gate: failed to resolve scsi0 disk for ${SMOKE_VMID}" >&2
  exit 21
fi

LV_NAME="${DISK_REF#*:}"
SMOKE_LV="/dev/pve/${LV_NAME}"
if [[ ! -b "${SMOKE_LV}" ]]; then
  echo "smoke gate: expected LVM block device not found: ${SMOKE_LV}" >&2
  exit 22
fi

kpartx -a "${SMOKE_LV}" >/dev/null
MAPPER_BASE="pve-${LV_NAME//-/--}"
SMOKE_PART="/dev/mapper/${MAPPER_BASE}p3"
if [[ ! -b "${SMOKE_PART}" ]]; then
  echo "smoke gate: expected partition mapper not found: ${SMOKE_PART}" >&2
  ls -l /dev/mapper/ | sed -n '1,200p' >&2 || true
  exit 23
fi

mkdir -p "${SMOKE_MNT}"
mount -o ro "${SMOKE_PART}" "${SMOKE_MNT}"

RW_ROOT="$(find "${SMOKE_MNT}/boot" -mindepth 2 -maxdepth 2 -type d -name rw | head -n1 || true)"
if [[ -z "${RW_ROOT}" ]]; then
  echo "smoke gate: unable to locate VyOS rw root under ${SMOKE_MNT}/boot" >&2
  exit 24
fi

CONFIG_BOOT="${RW_ROOT}/opt/vyatta/etc/config/config.boot"
if [[ ! -f "${CONFIG_BOOT}" ]]; then
  echo "smoke gate: config.boot missing: ${CONFIG_BOOT}" >&2
  exit 25
fi
if ! grep -q "host-name \"${SMOKE_MARKER}\"" "${CONFIG_BOOT}"; then
  echo "smoke gate: expected host-name marker '${SMOKE_MARKER}' not found in config.boot" >&2
  sed -n '1,220p' "${CONFIG_BOOT}" >&2 || true
  exit 26
fi

RESULT_JSON="${RW_ROOT}/var/lib/cloud/data/result.json"
if [[ -f "${RESULT_JSON}" ]]; then
  python3 - "${RESULT_JSON}" <<'PY'
import json, sys
path = sys.argv[1]
data = json.loads(open(path, "r", encoding="utf-8").read())
errors = ((data.get("v1") or {}).get("errors") or [])
ignored_substrings = (
    "Unknown network config version: None",
)
remaining = [
    err for err in errors
    if not any(marker in str(err) for marker in ignored_substrings)
]
if remaining:
    raise SystemExit(f"cloud-init reported errors during template smoke boot: {remaining}")
PY
fi
EOF

  ssh_run \
    "TEMPLATE_VMID='${TEMPLATE_VMID}' TEMPLATE_NAME='${TEMPLATE_NAME}' STORAGE_VM='${STORAGE_VM}' CI_USERNAME='${CI_USERNAME}' TEMPLATE_SMOKE_VMID='${TEMPLATE_SMOKE_VMID}' TEMPLATE_SMOKE_BRIDGE='${TEMPLATE_SMOKE_BRIDGE}' TEMPLATE_SMOKE_WAIT_S='${TEMPLATE_SMOKE_WAIT_S}' TEMPLATE_SMOKE_MARKER='${TEMPLATE_SMOKE_MARKER}' bash -lc $(printf '%q' "${REMOTE_SMOKE}")"
fi

echo "template_vm_id=${TEMPLATE_VMID}"
