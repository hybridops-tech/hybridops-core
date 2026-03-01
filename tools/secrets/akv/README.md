# tools/secrets/akv

**Purpose:** Sync a mapped subset of Azure Key Vault secrets into the HybridOps runtime vault.

## Command

Preferred interface:

```bash
hyops secrets akv-sync --vault-name <akv-name> --scope all --vault-password-command 'tools/secrets/vault/vault-pass.sh'
```

Script entrypoint (delegates to `hyops`):

```bash
tools/secrets/akv/sync.sh --vault-name <akv-name> --scope netbox --vault-password-command 'tools/secrets/vault/vault-pass.sh'
```

## Map Contract

Map file format (`tools/secrets/akv/map/allowed.csv`):

```csv
scope,ENV_KEY,AKV_SECRET_NAME
```

Rules:

- `scope`: logical grouping (`all` syncs every row).
- `ENV_KEY`: key written into encrypted runtime vault env.
- `AKV_SECRET_NAME`: source secret in Azure Key Vault.

## Safety

- Secret values are never printed.
- Sync fails fast on missing map rows, missing secrets, or vault auth errors.
- Vault auth must be explicit (`--vault-password-file` or `--vault-password-command`).
