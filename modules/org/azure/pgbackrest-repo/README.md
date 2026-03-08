# org/azure/pgbackrest-repo

Provision an Azure Storage Account and private Blob container to be used as a pgBackRest repository backend.

This module is intentionally infra-only:

- Creates Resource Group + Storage Account + Blob container.
- Applies baseline hardening (private container, TLS >= 1.2, no public blob access).
- Does **not** create or persist account keys.

For generic object storage use-cases (artifacts, logs, non-PostgreSQL backups), prefer `org/azure/object-repo`. This module keeps pgBackRest-oriented defaults.

## Normalized outputs

This module publishes the same cross-provider output contract as GCP/AWS modules:

- `repo_backend` (`azure`)
- `repo_provider` (`azure`)
- `repo_bucket_name` (container name)
- `repo_region`
- `repo_principal_type` (`storage_account_key` when shared key auth enabled)
- `repo_principal_name` (storage account name)
- `repo_credential_create_hint`

Azure aliases are also published: `resource_group_name`, `storage_account_name`, `container_name`, `account_key_hint`.

## Security model

Credentials are generated out-of-band and stored in the HyOps runtime vault.

Recommended flow:

1. Apply infra module.
2. Fetch storage account key using Azure CLI.
3. Store key in runtime vault (`PG_BACKUP_AZURE_ACCOUNT_KEY`).
4. Use in backup automation once Azure backend is enabled in `platform/postgresql-ha-backup`.

## Example

```bash
hyops preflight --env dev --strict \
  --module org/azure/pgbackrest-repo \
  --inputs "$HOME/.hybridops/core/app/modules/org/azure/pgbackrest-repo/examples/inputs.min.yml"

hyops apply --env dev \
  --module org/azure/pgbackrest-repo \
  --inputs "$HOME/.hybridops/core/app/modules/org/azure/pgbackrest-repo/examples/inputs.min.yml"
```

Fetch account key (out-of-band):

```bash
# Use module outputs for rg/account names
az storage account keys list \
  --resource-group <resource_group_name> \
  --account-name <storage_account_name> \
  --query '[0].value' -o tsv
```

Store into vault:

```bash
hyops secrets set --env dev PG_BACKUP_AZURE_ACCOUNT_KEY='...'
```
