# tools/secrets/vault

**Purpose:** Provide a secure Ansible Vault password provider backed by `pass` (GPG-encrypted).

## Commands

- `vault-pass.sh` — print password to stdout for Ansible (`--vault-password-command`)
- `vault-pass.sh --status` — exit 0 if ready, else 1
- `vault-pass.sh --status-verbose` — print `ready` or `not ready`
- `vault-pass.sh --bootstrap` — interactive bootstrap (creates key if required; stores entry)
- `vault-pass.sh --bootstrap-stdin` — store entry from stdin (requires pass already initialized)
- `vault-pass.sh --reset` — delete stored entry

## Recommended integration

```bash
hyops init proxmox --vault-password-command 'tools/secrets/vault/vault-pass.sh' ...
```

## Operational constraints

- Requires `pass` and `gpg`.
- Optionally verifies the password against an existing vault file when `VAULT_PASS_VERIFY_FILE` is set.
