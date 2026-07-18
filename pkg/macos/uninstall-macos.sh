#!/bin/sh
set -eu

package_id="tech.hybridops.core"
metadata_dir="/usr/local/share/hybridops-core"
purge_runtime="false"

if [ "${1:-}" = "--purge-runtime" ]; then
  purge_runtime="true"
elif [ "$#" -ne 0 ]; then
  echo "usage: sudo uninstall-macos.sh [--purge-runtime]" >&2
  exit 2
fi

if [ "$(/usr/bin/id -u)" -ne 0 ]; then
  echo "Run this command with sudo." >&2
  exit 2
fi

installed_home=""
if [ -f "${metadata_dir}/installed-home" ]; then
  installed_home=$(/bin/cat "${metadata_dir}/installed-home")
fi
case "${installed_home}" in
  /Users/*) ;;
  "") ;;
  *)
    echo "Refusing an unexpected installed home path: ${installed_home}" >&2
    exit 2
    ;;
esac

if [ -f /usr/local/bin/hyops ] && \
  /usr/bin/grep -Fq '# HybridOps.Core macOS package launcher' /usr/local/bin/hyops; then
  /bin/rm -f /usr/local/bin/hyops
fi

launcher_app="/Applications/HybridOps.Core.app"
launcher_plist="${launcher_app}/Contents/Info.plist"
if [ -f "${launcher_plist}" ] && \
  [ "$(/usr/libexec/PlistBuddy -c 'Print :CFBundleIdentifier' "${launcher_plist}" 2>/dev/null || true)" = \
    "tech.hybridops.core.launcher" ]; then
  /bin/rm -rf "${launcher_app}"
fi

if [ -n "${installed_home}" ]; then
  launcher="${installed_home}/.hybridops/config/macos-shell.command"
  if [ -f "${launcher}" ] && \
    /usr/bin/grep -Fq 'HybridOps.Core ready.' "${launcher}"; then
    /bin/rm -f "${launcher}"
  fi

  if [ "${purge_runtime}" = "true" ]; then
    /bin/rm -rf "${installed_home}/.hybridops"
  else
    /bin/rm -rf "${installed_home}/.hybridops/core"
  fi

  if [ -f "${installed_home}/.local/bin/hyops" ] && \
    /usr/bin/grep -Fq 'HYOPS_CORE_ROOT=' "${installed_home}/.local/bin/hyops"; then
    /bin/rm -f "${installed_home}/.local/bin/hyops"
  fi
fi

/usr/sbin/pkgutil --forget "${package_id}" >/dev/null 2>&1 || true
/bin/rm -rf "${metadata_dir}"

if [ "${purge_runtime}" = "true" ]; then
  echo "HybridOps.Core and its runtime data were removed."
else
  echo "HybridOps.Core was removed. Runtime environments, logs and vault data were retained."
fi
