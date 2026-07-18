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
RESOURCES_DIR="${WORK_DIR}/resources"
APP_DIR="${ROOT_DIR}/Applications/HybridOps.Core.app"
APP_CONTENTS_DIR="${APP_DIR}/Contents"
APP_MACOS_DIR="${APP_CONTENTS_DIR}/MacOS"
APP_RESOURCES_DIR="${APP_CONTENTS_DIR}/Resources"
ICONSET_DIR="${WORK_DIR}/hybridops.iconset"
COMPONENT_PKG="${WORK_DIR}/hybridops-core-component.pkg"
DISTRIBUTION_XML="${WORK_DIR}/distribution.xml"
mkdir -p \
  "${ROOT_DIR}/usr/local/share/hybridops-core" \
  "${APP_MACOS_DIR}" \
  "${APP_RESOURCES_DIR}" \
  "${ICONSET_DIR}" \
  "${SCRIPTS_DIR}" \
  "${RESOURCES_DIR}"

install -m 0755 "${SCRIPT_DIR}/macos/uninstall-macos.sh" \
  "${ROOT_DIR}/usr/local/share/hybridops-core/uninstall-macos.sh"
install -m 0755 "${SCRIPT_DIR}/macos/macos-shell.command" \
  "${ROOT_DIR}/usr/local/share/hybridops-core/macos-shell.command"
install -m 0755 "${SCRIPT_DIR}/macos/app/HybridOps.Core" \
  "${APP_MACOS_DIR}/HybridOps.Core"
python3 - "${SCRIPT_DIR}/macos/app/Info.plist" "${APP_CONTENTS_DIR}/Info.plist" "${VERSION}" <<'PY'
from pathlib import Path
import sys

source = Path(sys.argv[1]).read_text(encoding="utf-8")
Path(sys.argv[2]).write_text(
    source.replace("__HYOPS_VERSION__", sys.argv[3]),
    encoding="utf-8",
)
PY

command -v sips >/dev/null 2>&1 || { echo "ERR: sips is required" >&2; exit 2; }
command -v iconutil >/dev/null 2>&1 || { echo "ERR: iconutil is required" >&2; exit 2; }
ICON_SOURCE="${REPO_ROOT}/assets/macos/hybridops.png"
[[ -f "${ICON_SOURCE}" ]] || { echo "ERR: macOS launcher icon not found: ${ICON_SOURCE}" >&2; exit 2; }
for specification in \
  "16 icon_16x16.png" \
  "32 icon_16x16@2x.png" \
  "32 icon_32x32.png" \
  "64 icon_32x32@2x.png" \
  "128 icon_128x128.png" \
  "256 icon_128x128@2x.png" \
  "256 icon_256x256.png" \
  "512 icon_256x256@2x.png" \
  "512 icon_512x512.png" \
  "1024 icon_512x512@2x.png"; do
  read -r size filename <<<"${specification}"
  sips -z "${size}" "${size}" "${ICON_SOURCE}" \
    --out "${ICONSET_DIR}/${filename}" >/dev/null
done
iconutil -c icns "${ICONSET_DIR}" -o "${APP_RESOURCES_DIR}/hybridops.icns"

install -m 0755 "${SCRIPT_DIR}/macos/preinstall" "${SCRIPTS_DIR}/preinstall"
install -m 0755 "${SCRIPT_DIR}/macos/postinstall" "${SCRIPTS_DIR}/postinstall"
install -m 0644 "${ARCHIVE}" "${SCRIPTS_DIR}/release.tar.gz"
install -m 0644 "${SCRIPT_DIR}/macos/resources/welcome.html" "${RESOURCES_DIR}/welcome.html"
install -m 0644 "${SCRIPT_DIR}/macos/resources/conclusion.html" "${RESOURCES_DIR}/conclusion.html"
install -m 0644 "${SCRIPT_DIR}/macos/resources/hybridops.svg" "${RESOURCES_DIR}/hybridops.svg"
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

productbuild --synthesize --package "${COMPONENT_PKG}" "${DISTRIBUTION_XML}"
python3 - "${DISTRIBUTION_XML}" <<'PY'
from pathlib import Path
import sys
import xml.etree.ElementTree as ET

path = Path(sys.argv[1])
tree = ET.parse(path)
root = tree.getroot()
entries = (
    ("title", None, "HybridOps.Core"),
    ("welcome", "welcome.html", None),
    ("conclusion", "conclusion.html", None),
)
for index, (tag, filename, text) in enumerate(entries):
    element = ET.Element(tag)
    if filename:
        element.set("file", filename)
    element.text = text
    root.insert(index, element)
tree.write(path, encoding="utf-8", xml_declaration=True)
PY

product_args=(
  --distribution "${DISTRIBUTION_XML}"
  --package-path "${WORK_DIR}"
  --resources "${RESOURCES_DIR}"
)
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
