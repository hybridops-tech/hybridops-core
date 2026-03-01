# drivers/secrets

**Purpose:** Provide optional secrets helpers used by HybridOps.Core targets and drivers.

This directory is not a Driver API implementation. It is an operator-facing helper surface for secure secret handling and syncing strategies.

## Layout

```text
tools/secrets/
  vault/
    vault-pass.sh
    README.md
  akv/
    sync.sh
    map/
      allowed.csv
    README.md
  gsm/
    map/
      allowed.csv
    README.md
  hashicorp-vault/
    map/
      allowed.csv
    README.md
```

## Usage

### Vault password provider (recommended)

Bootstrap once:

```bash
tools/secrets/vault/vault-pass.sh --bootstrap
```

Use with `hyops init`:

```bash
hyops init proxmox --vault-password-command 'tools/secrets/vault/vault-pass.sh' ...
```

### Azure Key Vault sync

Sync mapped secrets into the runtime vault with `hyops`:

```bash
hyops secrets akv-sync \
  --vault-name <akv-name> \
  --scope all \
  --vault-password-command 'tools/secrets/vault/vault-pass.sh'
```

Or call the script entrypoint:

```bash
tools/secrets/akv/sync.sh --vault-name <akv-name> --scope netbox --vault-password-command 'tools/secrets/vault/vault-pass.sh'
```

### HashiCorp Vault sync

Sync mapped secrets from an external HashiCorp Vault authority into the runtime vault cache:

```bash
VAULT_ADDR=https://vault.example.com \
VAULT_TOKEN=... \
hyops secrets vault-sync \
  --env dev \
  --scope dr \
  --vault-password-command 'tools/secrets/vault/vault-pass.sh'
```

### GCP Secret Manager sync

Sync mapped secrets from GCP Secret Manager into the runtime vault cache:

```bash
hyops secrets gsm-sync \
  --env dev \
  --scope dr \
  --vault-password-command 'tools/secrets/vault/vault-pass.sh'
```

Persist the current runtime-vault values back into GCP Secret Manager:

```bash
hyops secrets gsm-persist \
  --env dev \
  --scope dr \
  --vault-password-command 'tools/secrets/vault/vault-pass.sh'
```

### Non-interactive runs

Use a password command or password file. Avoid passing secrets in CLI args.

## Notes

- `vault-pass.sh` uses `pass` + GPG to store the Ansible Vault password.
- `akv-sync` reads only mapped keys and never prints secret values.
- `gsm-sync` reads only mapped keys and never prints secret values.
- `vault-sync` reads only mapped keys and never prints secret values.
- Configure mappings in `tools/secrets/akv/map/allowed.csv`.
- Configure GCP Secret Manager mappings in `tools/secrets/gsm/map/allowed.csv`.
- Configure HashiCorp Vault mappings in `tools/secrets/hashicorp-vault/map/allowed.csv`.
