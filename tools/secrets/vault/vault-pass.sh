#!/usr/bin/env bash
# purpose: Ansible Vault password provider backed by pass
# adr: ADR-0610-env-bootstrap-scripts
# maintainer: HybridOps.Studio

set -euo pipefail
umask 077

ENTRY="${VAULT_PASS_ENTRY:-hybridops/ansible-vault}"
HOME_STORE="${HOME}/.password-store"
STORE_DIR="${PASSWORD_STORE_DIR:-$HOME_STORE}"

GPG_IDENTITY="${VAULT_PASS_GPG_IDENTITY:-HybridOps Vault (local)}"
GPG_TTL="${VAULT_PASS_GPG_TTL:-1y}"
PASS_TIMEOUT_S="${VAULT_PASS_TIMEOUT_S:-6}"
AUTO_UNLOCK="${VAULT_PASS_AUTO_UNLOCK:-1}"
UNLOCK_TIMEOUT_S="${VAULT_PASS_UNLOCK_TIMEOUT_S:-20}"

# Optional: verify password decrypts this vault file before storing.
# If unset, defaults to <git-root>/control/secrets.vault.env when available.
VERIFY_FILE="${VAULT_PASS_VERIFY_FILE:-}"

ACTION="print" # print | status | status-verbose | bootstrap | bootstrap-stdin | reset

usage() {
  cat >&2 <<'USAGE'
Usage:
  vault-pass.sh                    Print vault password to stdout (Ansible)
  vault-pass.sh --status           Exit 0 if ready, else 1 (no output)
  vault-pass.sh --status-verbose   Print: ready | not ready
  vault-pass.sh --bootstrap        Ensure pass/gpg config and store entry (interactive)
  vault-pass.sh --bootstrap-stdin  Store entry (reads from stdin; requires pass already initialized)
  vault-pass.sh --reset            Remove entry and require bootstrap again

Env:
  VAULT_PASS_ENTRY          pass entry name (default: hybridops/ansible-vault)
  PASSWORD_STORE_DIR        pass store root (default: ~/.password-store)
  VAULT_PASS_GPG_IDENTITY   gpg uid for auto-generated key (bootstrap only)
  VAULT_PASS_GPG_TTL        gpg key ttl (bootstrap only; default: 1y)
  VAULT_PASS_VERIFY_FILE    vault file path to verify before storing (optional)
  VAULT_PASS_TIMEOUT_S      max seconds for pass show/decrypt checks (default: 6)
  VAULT_PASS_AUTO_UNLOCK    set to 1 to attempt interactive unlock automatically (default: 1)
  VAULT_PASS_UNLOCK_TIMEOUT_S  max seconds for interactive unlock attempt (default: 20)
USAGE
}

log() { echo "[vault-pass] $*" >&2; }
die() { log "ERROR: $*"; exit 2; }
have() { command -v "$1" >/dev/null 2>&1; }

_pass_show() {
  local opts="${1:-}"
  local timeout_s="${2:-$PASS_TIMEOUT_S}"
  if have timeout; then
    if [[ -n "$opts" ]]; then
      PASSWORD_STORE_GPG_OPTS="$opts" timeout --foreground "${timeout_s}s" pass show "$ENTRY"
    else
      timeout --foreground "${timeout_s}s" pass show "$ENTRY"
    fi
  else
    if [[ -n "$opts" ]]; then
      PASSWORD_STORE_GPG_OPTS="$opts" pass show "$ENTRY"
    else
      pass show "$ENTRY"
    fi
  fi
}

_tty_name() {
  local t=""
  if [[ -t 0 ]]; then
    t="$(tty 2>/dev/null || true)"
  fi
  if [[ -z "${t:-}" || "${t:-}" == "not a tty" ]]; then
    if { exec 9</dev/tty; } 2>/dev/null; then
      t="$(tty <&9 2>/dev/null || true)"
      exec 9<&-
    fi
  fi
  t="$(printf '%s' "${t:-}" | tr -d '\r\n')"
  [[ -n "${t:-}" && "${t:-}" != "not a tty" ]] || return 1
  printf '%s' "$t"
}

need_tty() {
  _tty_name >/dev/null 2>&1 || die "TTY required (no controlling terminal)"
}

canon_file() { printf '%s/%s.gpg\n' "$1" "$ENTRY"; }

guard_store_path() {
  local d="$1"
  [[ -n "$d" ]] || die "store dir empty"
  [[ "$d" == "$HOME_STORE"* ]] || die "refusing to operate outside: $HOME_STORE"
}

ensure_store_dir() {
  guard_store_path "$STORE_DIR"
  mkdir -p -- "$STORE_DIR"
}

ensure_gpg_tty() {
  # Pinentry often fails in fresh shells if gpg-agent still points to an old TTY.
  # Resolve a controlling terminal only when available; remain silent in non-interactive runs.
  local t=""
  t="$(_tty_name || true)"
  [[ -n "${t:-}" ]] || return 0

  export GPG_TTY="$t"
  have gpgconf && gpgconf --launch gpg-agent >/dev/null 2>&1 || true
  have gpg-connect-agent && gpg-connect-agent updatestartuptty /bye >/dev/null 2>&1 || true
}

ensure_gpg_runtime() {
  local gnupg_dir="${HOME}/.gnupg"
  local agent_conf="${gnupg_dir}/gpg-agent.conf"
  local changed=0
  local pinentry_bin=""

  mkdir -p -- "$gnupg_dir"
  chmod 700 "$gnupg_dir" >/dev/null 2>&1 || true

  if ! grep -q '^pinentry-program ' "$agent_conf" 2>/dev/null; then
    for cand in pinentry-curses pinentry-tty pinentry; do
      if pinentry_bin="$(command -v "$cand" 2>/dev/null || true)" && [[ -n "${pinentry_bin:-}" ]]; then
        break
      fi
    done
    if [[ -n "${pinentry_bin:-}" ]]; then
      printf 'pinentry-program %s\n' "$pinentry_bin" >>"$agent_conf"
      changed=1
    fi
  fi

  if ! grep -q '^allow-loopback-pinentry$' "$agent_conf" 2>/dev/null; then
    printf 'allow-loopback-pinentry\n' >>"$agent_conf"
    changed=1
  fi

  if [[ "$changed" == "1" ]]; then
    have gpgconf && gpgconf --kill gpg-agent >/dev/null 2>&1 || true
    have gpgconf && gpgconf --launch gpg-agent >/dev/null 2>&1 || true
  fi
}

gpg_primary_fpr() {
  gpg --list-secret-keys --with-colons 2>/dev/null     | awk -F: '
        $1=="sec"{sec=1; next}
        sec && $1=="fpr"{print $10; exit}
      '
}

ensure_gpg_key() {
  have gpg || die "gpg not installed"
  ensure_gpg_tty

  local fpr=""
  fpr="$(gpg_primary_fpr || true)"
  [[ -n "$fpr" ]] && return 0

  need_tty
  gpg --quick-generate-key "$GPG_IDENTITY" default default "$GPG_TTL" >/dev/null 2>&1 || true

  fpr="$(gpg_primary_fpr || true)"
  [[ -n "$fpr" ]] || die "gpg key creation failed"
}

ensure_pass_init() {
  have pass || die "pass not installed"
  ensure_store_dir

  local fpr gpg_id_file
  fpr="$(gpg_primary_fpr || true)"
  [[ -n "$fpr" ]] || die "no gpg key available"

  gpg_id_file="${STORE_DIR}/.gpg-id"
  [[ -f "$gpg_id_file" ]] && return 0

  pass init "$fpr" >/dev/null 2>&1 || die "pass init failed"
  [[ -f "$gpg_id_file" ]] || die "pass init did not create .gpg-id"
}

stored() {
  have pass || return 1
  [[ -e "$(canon_file "$STORE_DIR")" ]] || return 1
  # Fail fast if gpg is locked (no pinentry prompts in non-interactive use).
  if _pass_show "--pinentry-mode=error ${PASSWORD_STORE_GPG_OPTS:-}" >/dev/null 2>&1; then
    return 0
  fi
  return 1
}

_resolve_verify_file() {
  [[ -n "$VERIFY_FILE" ]] && return 0

  local script_dir repo_root candidate
  script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
  repo_root="$(cd -- "${script_dir}/../../../../" && pwd)"
  candidate="${repo_root}/control/secrets.vault.env"
  [[ -f "$candidate" ]] && VERIFY_FILE="$candidate" || true
}

_verify_vault_password_or_die() {
  _resolve_verify_file

  [[ -n "${VERIFY_FILE}" ]] || return 0
  [[ -f "${VERIFY_FILE}" ]] || die "verify file not found: ${VERIFY_FILE}"
  have ansible-vault || die "ansible-vault not found (cannot verify password)"

  local tmp=""
  tmp="$(mktemp)"
  chmod 600 "$tmp"
  trap '[[ -n "${tmp:-}" ]] && rm -f -- "${tmp}"' RETURN

  printf '%s\n' "$1" >"$tmp"
  ansible-vault view --vault-password-file "$tmp" "$VERIFY_FILE" >/dev/null 2>&1     || die "invalid vault password for: ${VERIFY_FILE}"
}

_read_secret_tty() {
  local pw=""
  need_tty
  { exec 9<>/dev/tty; } 2>/dev/null || die "TTY required (no controlling terminal)"
  printf '%s' "Vault password: " >&9
  IFS= read -rs pw <&9 || true
  printf '\n' >&9
  exec 9<&-
  exec 9>&-
  pw="$(printf '%s' "${pw:-}" | tr -d '\r\n')"
  [[ -n "$pw" ]] || die "empty password provided"
  printf '%s' "$pw"
}

bootstrap() {
  have pass || die "pass not installed"
  have gpg  || die "gpg not installed"

  ensure_store_dir
  ensure_gpg_key
  ensure_pass_init

  local pw
  pw="$(_read_secret_tty)"

  _verify_vault_password_or_die "$pw"

  printf '%s\n' "$pw" | pass insert -m "$ENTRY" >/dev/null
  [[ -e "$(canon_file "$STORE_DIR")" ]] || die "expected file not found"
  log "stored: $ENTRY"
}

bootstrap_stdin() {
  have pass || die "pass not installed"
  have gpg  || die "gpg not installed"

  ensure_store_dir
  [[ -f "${STORE_DIR}/.gpg-id" ]] || die "pass not initialized (run --bootstrap)"
  pass show "$ENTRY" >/dev/null 2>&1 && die "entry already exists (run --reset to replace)"

  local pw=""
  IFS= read -r pw || true
  pw="$(printf '%s' "${pw:-}" | tr -d '\r\n')"
  [[ -n "$pw" ]] || die "empty password provided"

  _verify_vault_password_or_die "$pw"

  printf '%s\n' "$pw" | pass insert -m "$ENTRY" >/dev/null
  [[ -e "$(canon_file "$STORE_DIR")" ]] || die "expected file not found"
  log "stored: $ENTRY"
}

reset_all() {
  have pass || die "pass not installed"
  guard_store_path "$STORE_DIR"

  local f_store f_home entry_dir
  f_store="$(canon_file "$STORE_DIR")"
  f_home="$(canon_file "$HOME_STORE")"
  entry_dir="$(dirname "$f_store")"

  pass rm -f "$ENTRY" >/dev/null 2>&1 || true
  rm -f -- "$f_store" >/dev/null 2>&1 || true
  [[ "$STORE_DIR" == "$HOME_STORE" ]] || rm -f -- "$f_home" >/dev/null 2>&1 || true

  rmdir --ignore-fail-on-non-empty "$entry_dir" >/dev/null 2>&1 || true
  have gpgconf && gpgconf --kill gpg-agent >/dev/null 2>&1 || true

  [[ ! -e "$f_store" ]] || die "reset failed: file still exists"
  [[ "$STORE_DIR" == "$HOME_STORE" || ! -e "$f_home" ]] || die "reset failed: file still exists"

  if pass show "$ENTRY" >/dev/null 2>&1; then
    die "reset failed: pass still reads entry"
  fi

  log "reset complete"
}

print_password() {
  local pw="" tmp="" rc=0
  tmp="$(mktemp)"
  set +e
  _pass_show "--pinentry-mode=error ${PASSWORD_STORE_GPG_OPTS:-}" >"$tmp" 2>/dev/null
  rc="$?"
  set -e
  if [[ "$rc" != "0" ]]; then
    rm -f -- "$tmp" || true
    if [[ "$rc" == "124" ]]; then
      die "pass show timed out after ${PASS_TIMEOUT_S}s; check gpg/pinentry and try again"
    fi
    die "cannot decrypt entry: $ENTRY (unlock gpg via: hyops vault status-verbose)"
  fi
  pw="$(head -n1 "$tmp" | tr -d '\r\n')"
  rm -f -- "$tmp" || true
  [[ -n "$pw" ]] || die "empty password from pass entry: $ENTRY"
  printf '%s\n' "$pw"
}

try_unlock() {
  # Best-effort: unlock the GPG key in interactive shells so hyops can proceed
  # without requiring manual `export GPG_TTY=...` or direct `pass show` calls.
  # Do not attempt interactive unlock if stdin is not a TTY (pipes/CI).
  [[ -t 0 ]] || return 1
  have pass || return 1
  ensure_gpg_runtime
  ensure_gpg_tty

  { exec 9<>/dev/tty; } 2>/dev/null || return 1
  if ! _pass_show "" "$UNLOCK_TIMEOUT_S" <&9 >/dev/null 2>&9; then
    exec 9<&-
    exec 9>&-
    return 1
  fi
  exec 9<&-
  exec 9>&-
  return 0
}

while [[ $# -gt 0 ]]; do
  case "${1:-}" in
    --bootstrap) ACTION="bootstrap"; shift ;;
    --bootstrap-stdin) ACTION="bootstrap-stdin"; shift ;;
    --reset) ACTION="reset"; shift ;;
    --status) ACTION="status"; shift ;;
    --status-verbose) ACTION="status-verbose"; shift ;;
    -h|--help) usage; exit 0 ;;
    *) die "unknown option: $1" ;;
  esac
done

ensure_gpg_tty

case "$ACTION" in
  status)
    if stored; then exit 0; fi
    exit 1
    ;;
  status-verbose)
    # stdout must remain: ready|not ready (scripts/CI depend on this); details go to stderr.
    if ! have pass; then
      echo "not ready"
      log "missing command: pass"
      exit 1
    fi

    if [[ ! -e "$(canon_file "$STORE_DIR")" ]]; then
      echo "not ready"
      log "entry not found: $ENTRY (run: hyops vault bootstrap)"
      exit 1
    fi

    tmp_err="$(mktemp)"
    set +e
    _pass_show "--pinentry-mode=error ${PASSWORD_STORE_GPG_OPTS:-}" >/dev/null 2>"$tmp_err"
    rc="$?"
    set -e
    err="$(cat "$tmp_err" 2>/dev/null || true)"
    rm -f -- "$tmp_err" || true

    if [[ "$rc" == "0" ]]; then
      echo "ready"
      exit 0
    fi
    if [[ "$rc" == "124" ]]; then
      err="timeout after ${PASS_TIMEOUT_S}s while reading pass entry"
    fi

    echo "not ready"
    log "cannot decrypt entry: $ENTRY (rc=$rc)."
    if [[ -n "${err:-}" ]]; then
      log "pass/gpg error: ${err}"
    fi
    log "If this is a fresh shell, unlock your GPG key by running: hyops vault password >/dev/null"
    log "(or: pass show \"$ENTRY\" >/dev/null)"
    exit 1
    ;;
  bootstrap)
    bootstrap
    ;;
  bootstrap-stdin)
    bootstrap_stdin
    ;;
  reset)
    reset_all
    ;;
  print)
    have pass || die "pass not installed"
    if [[ ! -e "$(canon_file "$STORE_DIR")" ]]; then
      die "entry not ready (run --bootstrap)"
    fi

    if ! stored; then
      # Auto-unlock by default (bounded by UNLOCK_TIMEOUT_S); set VAULT_PASS_AUTO_UNLOCK=0 to force fail-fast.
      if [[ "$AUTO_UNLOCK" == "1" ]]; then
        try_unlock || die "entry exists but cannot decrypt (unlock gpg via: hyops vault password >/dev/null OR: pass show \"$ENTRY\" >/dev/null)"
      else
        die "entry exists but cannot decrypt (unlock gpg via: hyops vault password >/dev/null OR: pass show \"$ENTRY\" >/dev/null)"
      fi
      stored || die "entry exists but still cannot decrypt (check pinentry/gpg-agent configuration)"
    fi

    print_password
    ;;
esac
