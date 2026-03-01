#!/usr/bin/env bash
# purpose: Sync selected secrets from Azure Key Vault into HybridOps runtime vault.
# Architecture Decision: ADR-0020-secrets-strategy
# maintainer: HybridOps.Studio

set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
CORE_ROOT="$(cd -- "${SCRIPT_DIR}/../../.." && pwd)"

if command -v hyops >/dev/null 2>&1; then
  exec hyops secrets akv-sync --core-root "${CORE_ROOT}" "$@"
fi

if command -v python3 >/dev/null 2>&1; then
  export PYTHONPATH="${CORE_ROOT}${PYTHONPATH:+:${PYTHONPATH}}"
  exec python3 -m hyops.cli secrets akv-sync --core-root "${CORE_ROOT}" "$@"
fi

echo "ERR: missing command: hyops (or python3 fallback)." >&2
exit 2
