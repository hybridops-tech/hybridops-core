#!/usr/bin/env bash
# purpose: Payload copy and permission normalization helpers for installer.
# Architecture Decision: ADR-N/A (bootstrap installer)
# maintainer: HybridOps.Tech

hyops_install_copy_payload() {
  echo "[install] copying payload"
  mkdir -p "${APP_DIR}"
  cp -a "${SRC_ROOT}/." "${APP_DIR}/"
  echo "[install] hardening shipped blueprint payload"
  hyops_install_set_blueprint_payload_read_only "${APP_DIR}"
}

hyops_install_normalize_payload_permissions() {
  echo "[install] normalizing installed payload permissions"
  chmod -R a+rX "${PREFIX}"
  hyops_install_set_blueprint_payload_read_only "${APP_DIR}"
}

hyops_install_install_vault_helper() {
  if [[ -f "${VAULT_PASS_SRC}" ]]; then
    echo "[install] installing vault helper"
    cp -f "${VAULT_PASS_SRC}" "${VAULT_PASS_DST}"
    chmod 0755 "${VAULT_PASS_DST}"
  fi
}
