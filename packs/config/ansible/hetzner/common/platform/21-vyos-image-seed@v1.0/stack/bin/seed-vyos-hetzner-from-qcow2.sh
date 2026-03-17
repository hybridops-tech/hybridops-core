#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
usage: seed-vyos-hetzner-from-qcow2.sh --source-url URL --public-base-url URL --bind-port PORT --architecture ARCH --compression COMP --description TEXT --seed-tool TOOL [--seed-location NAME] [--seed-server-type NAME] [--labels CSV]

Downloads a qcow2-based VyOS artifact, converts it to raw, serves it temporarily
from the execution host, and delegates the actual Hetzner image upload to
hcloud-upload-image.

The public base URL must be reachable from the Hetzner rescue environment and
should usually point back to the execution host, for example:
  http://203.0.113.10:18080
EOF
}

require_cmd() {
  command -v "$1" >/dev/null 2>&1 || {
    echo "missing required command: $1" >&2
    exit 1
  }
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
    echo "service account JSON is missing client_email/private_key" >&2
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
        echo "private GCS source requires gcloud/gsutil or HYOPS_VYOS_GCS_SA_JSON_FILE" >&2
        exit 7
      fi
      ;;
    https://storage.googleapis.com/*)
      if curl -fsSL "$url" -o "$output_file"; then
        return 0
      fi
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
        echo "GCS source could not be downloaded via curl and no authenticated GCS client is available" >&2
        exit 7
      fi
      ;;
    file://*)
      local local_path
      local_path="${url#file://}"
      if [[ ! -f "$local_path" ]]; then
        echo "local source artifact not found: ${local_path}" >&2
        exit 8
      fi
      cp "$local_path" "$output_file"
      ;;
    /*)
      if [[ ! -f "$url" ]]; then
        echo "local source artifact not found: ${url}" >&2
        exit 8
      fi
      cp "$url" "$output_file"
      ;;
    *)
      curl -fsSL --retry 5 --retry-delay 2 -o "$output_file" "$url"
      ;;
  esac
}

SOURCE_URL=""
PUBLIC_BASE_URL=""
BIND_PORT=""
ARCHITECTURE=""
COMPRESSION=""
DESCRIPTION=""
SEED_TOOL=""
SEED_LOCATION=""
SEED_SERVER_TYPE=""
LABELS=""
gcs_sa_json_file="${HYOPS_VYOS_GCS_SA_JSON_FILE:-}"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --source-url)
      SOURCE_URL="${2:-}"
      shift 2
      ;;
    --public-base-url)
      PUBLIC_BASE_URL="${2:-}"
      shift 2
      ;;
    --bind-port)
      BIND_PORT="${2:-}"
      shift 2
      ;;
    --architecture)
      ARCHITECTURE="${2:-}"
      shift 2
      ;;
    --compression)
      COMPRESSION="${2:-}"
      shift 2
      ;;
    --description)
      DESCRIPTION="${2:-}"
      shift 2
      ;;
    --seed-tool)
      SEED_TOOL="${2:-}"
      shift 2
      ;;
    --seed-location)
      SEED_LOCATION="${2:-}"
      shift 2
      ;;
    --seed-server-type)
      SEED_SERVER_TYPE="${2:-}"
      shift 2
      ;;
    --labels)
      LABELS="${2:-}"
      shift 2
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "unknown argument: $1" >&2
      usage >&2
      exit 1
      ;;
  esac
done

[[ -n "$SOURCE_URL" ]] || { echo "--source-url is required" >&2; exit 1; }
[[ -n "$PUBLIC_BASE_URL" ]] || { echo "--public-base-url is required" >&2; exit 1; }
[[ -n "$BIND_PORT" ]] || { echo "--bind-port is required" >&2; exit 1; }
if [[ -z "$ARCHITECTURE" && -z "$SEED_SERVER_TYPE" ]]; then
  echo "--architecture is required when --seed-server-type is not set" >&2
  exit 1
fi
[[ -n "$COMPRESSION" ]] || { echo "--compression is required" >&2; exit 1; }
[[ -n "$DESCRIPTION" ]] || { echo "--description is required" >&2; exit 1; }
[[ -n "$SEED_TOOL" ]] || { echo "--seed-tool is required" >&2; exit 1; }

require_cmd curl
require_cmd qemu-img
require_cmd python3
require_cmd "$SEED_TOOL"

tmpdir="$(mktemp -d)"
server_pid=""
cleanup() {
  if [[ -n "$server_pid" ]] && kill -0 "$server_pid" >/dev/null 2>&1; then
    kill "$server_pid" >/dev/null 2>&1 || true
    wait "$server_pid" >/dev/null 2>&1 || true
  fi
  rm -rf "$tmpdir"
}
trap cleanup EXIT

serve_dir="$tmpdir/serve"
mkdir -p "$serve_dir"

download_path="$tmpdir/source"
download_source_artifact "$SOURCE_URL" "$download_path"

qcow2_path="$tmpdir/source.qcow2"
lower_source="$(printf '%s' "$SOURCE_URL" | tr '[:upper:]' '[:lower:]')"
lower_source_path="${lower_source%%\?*}"
case "$lower_source_path" in
  *.qcow2)
    cp "$download_path" "$qcow2_path"
    ;;
  *.qcow2.xz)
    require_cmd xz
    xz -dc "$download_path" > "$qcow2_path"
    ;;
  *.qcow2.gz)
    require_cmd gzip
    gzip -dc "$download_path" > "$qcow2_path"
    ;;
  *.qcow2.bz2)
    require_cmd bzip2
    bzip2 -dc "$download_path" > "$qcow2_path"
    ;;
  *)
    echo "source URL must point to a qcow2 artifact (.qcow2, .qcow2.xz, .qcow2.gz, .qcow2.bz2)" >&2
    exit 1
    ;;
esac

raw_path="$tmpdir/source.raw"
qemu-img convert -p -f qcow2 -O raw "$qcow2_path" "$raw_path"

served_basename="wrapped-vyos.raw"
upload_compression="$COMPRESSION"
case "$COMPRESSION" in
  xz)
    require_cmd xz
    served_basename="${served_basename}.xz"
    xz -T0 -z -c "$raw_path" > "$serve_dir/$served_basename"
    ;;
  gz)
    require_cmd gzip
    served_basename="${served_basename}.gz"
    gzip -c "$raw_path" > "$serve_dir/$served_basename"
    ;;
  bz2)
    require_cmd bzip2
    served_basename="${served_basename}.bz2"
    bzip2 -c "$raw_path" > "$serve_dir/$served_basename"
    ;;
  raw|none)
    cp "$raw_path" "$serve_dir/$served_basename"
    ;;
  *)
    echo "unsupported compression: $COMPRESSION" >&2
    exit 1
    ;;
esac

python3 -m http.server "$BIND_PORT" --bind 0.0.0.0 --directory "$serve_dir" >"$tmpdir/http.log" 2>&1 &
server_pid="$!"

local_probe="http://127.0.0.1:${BIND_PORT}/${served_basename}"
for _ in 1 2 3 4 5 6 7 8 9 10; do
  if curl -fsS "$local_probe" >/dev/null 2>&1; then
    break
  fi
  sleep 1
done

image_url="${PUBLIC_BASE_URL%/}/${served_basename}"
cmd=(
  "$SEED_TOOL"
  upload
  --image-url "$image_url"
  --compression "$upload_compression"
  --description "$DESCRIPTION"
)
if [[ -n "$SEED_SERVER_TYPE" ]]; then
  cmd+=(--server-type "$SEED_SERVER_TYPE")
else
  cmd+=(--architecture "$ARCHITECTURE")
fi
if [[ -n "$SEED_LOCATION" ]]; then
  cmd+=(--location "$SEED_LOCATION")
fi
if [[ -n "$LABELS" ]]; then
  cmd+=(--labels "$LABELS")
fi

"${cmd[@]}"
