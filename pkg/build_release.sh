#!/usr/bin/env bash
set -euo pipefail

VERSION="${VERSION:-0.0.0-dev}"
OUT="hybridops-core-${VERSION}.tar.gz"

chmod 0755 bin/hyops || true
tar -czf "${OUT}" \
  --transform="s,^,hybridops-core-${VERSION}/," \
  README.md CHANGELOG.md LICENSE.txt install.sh toolchain hyops bin contracts drivers modules runbooks ci pkg pyproject.toml

echo "Built: ${OUT}"
