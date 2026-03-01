# tools/secrets/hashicorp-vault

**Purpose:** Map selected HashiCorp Vault secrets into the HybridOps runtime vault bundle for bootstrap, CI, and DR execution.

## Default map file

- `map/allowed.csv`

Format:

```text
scope,ENV_KEY,VAULT_SECRET_REF
```

Notes:

- `VAULT_SECRET_REF` supports `{env}` and `{scope}` placeholders.
- Secret refs default to `kv-v2` mount/path resolution.
- Append `#FIELD` to select a specific field from a secret payload.

Example:

```text
dr,PATRONI_SUPERUSER_PASSWORD,secret/hybridops/{env}/postgresql-ha#PATRONI_SUPERUSER_PASSWORD
```

## CLI

```bash
hyops init hashicorp-vault --env dev
hyops secrets vault-sync --env dev --scope dr
```

Authentication is provided via:

- the environment variable named by `--vault-token-env` (default `VAULT_TOKEN`), or
- the same token key cached in the runtime vault bundle after `hyops init hashicorp-vault --persist-token`

Optional namespace support uses `VAULT_NAMESPACE` or `--vault-namespace`.

Generated or explicitly set secrets can also be pushed upstream after local update:

```bash
hyops secrets ensure --env dev --persist vault PATRONI_SUPERUSER_PASSWORD
hyops secrets set --env dev --persist vault PATRONI_SUPERUSER_PASSWORD='...'
```
