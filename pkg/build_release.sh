#!/usr/bin/env bash
set -euo pipefail

VERSION="${VERSION:-0.0.0-dev}"
OUT="hybridops-core-${VERSION}.tar.gz"
MANIFEST="pkg/manifest.yml"

chmod 0755 bin/hyops || true

if [[ ! -f "${MANIFEST}" ]]; then
  echo "manifest not found: ${MANIFEST}" >&2
  exit 1
fi

mapfile -t include_paths < <(
  awk '
    BEGIN { in_include = 0 }
    /^include:[[:space:]]*$/ { in_include = 1; next }
    /^exclude:[[:space:]]*$/ { in_include = 0; next }
    in_include && /^[[:space:]]*-[[:space:]]+/ {
      line = $0
      sub(/^[[:space:]]*-[[:space:]]+/, "", line)
      print line
    }
  ' "${MANIFEST}"
)

if [[ ${#include_paths[@]} -eq 0 ]]; then
  echo "no include entries found in ${MANIFEST}" >&2
  exit 1
fi

files_to_package=()
for path in "${include_paths[@]}"; do
  if [[ -e "${path}" ]]; then
    files_to_package+=("${path}")
  else
    echo "warn: manifest include path missing, skipping: ${path}" >&2
  fi
done

if [[ ${#files_to_package[@]} -eq 0 ]]; then
  echo "no existing paths to package" >&2
  exit 1
fi

tar -czf "${OUT}" \
  --transform="s,^,hybridops-core-${VERSION}/," \
  "${files_to_package[@]}"

echo "Built: ${OUT}"
