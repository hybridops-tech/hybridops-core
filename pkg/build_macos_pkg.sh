#!/usr/bin/env bash
# purpose: Build a macOS installer package from a HybridOps.Core release archive.
# adr: ADR-0622
# maintainer: HybridOps.Tech

set -euo pipefail

usage() {
  cat <<'EOF'
usage: build_macos_pkg.sh --archive PATH --version VERSION [--output PATH] [--sign IDENTITY]

Build a macOS .pkg that runs the standard HybridOps.Core installer for the
signed-in user. The package is unsigned unless --sign is provided.
EOF
}

ARCHIVE=""
VERSION=""
OUTPUT=""
SIGN_IDENTITY=""

while [[ "$#" -gt 0 ]]; do
  case "$1" in
    --archive)
      ARCHIVE="${2:-}"
      shift 2
      ;;
    --version)
      VERSION="${2:-}"
      shift 2
      ;;
    --output)
      OUTPUT="${2:-}"
      shift 2
      ;;
    --sign)
      SIGN_IDENTITY="${2:-}"
      shift 2
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "ERR: unknown argument: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
done

[[ -n "${ARCHIVE}" ]] || { echo "ERR: --archive is required" >&2; exit 2; }
[[ -f "${ARCHIVE}" ]] || { echo "ERR: release archive not found: ${ARCHIVE}" >&2; exit 2; }
[[ -n "${VERSION}" ]] || { echo "ERR: --version is required" >&2; exit 2; }
[[ "${VERSION}" =~ ^[0-9]+([.][0-9]+){1,3}$ ]] || {
  echo "ERR: --version must contain two to four numeric components" >&2
  exit 2
}
[[ "$(uname -s)" == "Darwin" ]] || {
  echo "ERR: macOS package builds require macOS" >&2
  exit 2
}
command -v pkgbuild >/dev/null 2>&1 || { echo "ERR: pkgbuild is required" >&2; exit 2; }
command -v productbuild >/dev/null 2>&1 || { echo "ERR: productbuild is required" >&2; exit 2; }

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd -- "${SCRIPT_DIR}/.." && pwd)"
ARCHIVE="$(cd -- "$(dirname -- "${ARCHIVE}")" && pwd)/$(basename -- "${ARCHIVE}")"
if [[ -z "${OUTPUT}" ]]; then
  OUTPUT="${REPO_ROOT}/dist/releases/hybridops-core-${VERSION}-macos.pkg"
fi
mkdir -p "$(dirname -- "${OUTPUT}")"

WORK_DIR="$(mktemp -d)"
cleanup() {
  rm -rf "${WORK_DIR}"
}
trap cleanup EXIT

ROOT_DIR="${WORK_DIR}/root"
SCRIPTS_DIR="${WORK_DIR}/scripts"
COMPONENT_PKG="${WORK_DIR}/hybridops-core-component.pkg"
mkdir -p "${ROOT_DIR}/usr/local/share/hybridops-core" "${SCRIPTS_DIR}"

install -m 0755 "${SCRIPT_DIR}/macos/uninstall-macos.sh" \
  "${ROOT_DIR}/usr/local/share/hybridops-core/uninstall-macos.sh"
install -m 0755 "${SCRIPT_DIR}/macos/postinstall" "${SCRIPTS_DIR}/postinstall"
install -m 0644 "${ARCHIVE}" "${SCRIPTS_DIR}/release.tar.gz"
(
  cd "${SCRIPTS_DIR}"
  shasum -a 256 release.tar.gz > release.tar.gz.sha256
)

pkgbuild \
  --root "${ROOT_DIR}" \
  --scripts "${SCRIPTS_DIR}" \
  --identifier tech.hybridops.core \
  --version "${VERSION}" \
  --install-location / \
  "${COMPONENT_PKG}"

product_args=(--package "${COMPONENT_PKG}")
if [[ -n "${SIGN_IDENTITY}" ]]; then
  product_args+=(--sign "${SIGN_IDENTITY}")
fi
productbuild "${product_args[@]}" "${OUTPUT}"

pkgutil --check-signature "${OUTPUT}" || {
  if [[ -n "${SIGN_IDENTITY}" ]]; then
    echo "ERR: package signature verification failed" >&2
    exit 2
  fi
  echo "[pkg] unsigned package built for local testing"
}
echo "[pkg] ${OUTPUT}"
