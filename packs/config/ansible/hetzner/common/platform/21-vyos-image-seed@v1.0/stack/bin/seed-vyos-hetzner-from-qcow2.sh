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
curl -fsSL --retry 5 --retry-delay 2 -o "$download_path" "$SOURCE_URL"

qcow2_path="$tmpdir/source.qcow2"
lower_source="$(printf '%s' "$SOURCE_URL" | tr '[:upper:]' '[:lower:]')"
case "$lower_source" in
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
