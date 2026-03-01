# org/azure/object-repo

Provision a reusable Azure object repository (Storage Account + private Blob container).

This module is infra-only:

- Creates Resource Group + Storage Account + private container.
- Applies baseline hardening (TLS >= 1.2, no public blob access).
- Does **not** create or persist account keys.

## Normalized outputs

- `repo_backend` (`azure`)
- `repo_provider` (`azure`)
- `repo_bucket_name` (container)
- `repo_region`
- `repo_principal_type`
- `repo_principal_name` (storage account)
- `repo_credential_create_hint`

## Usage

```bash
hyops preflight --env <env> --strict \
  --module org/azure/object-repo \
  --inputs "$HYOPS_CORE_ROOT/modules/org/azure/object-repo/examples/inputs.min.yml"

hyops apply --env <env> \
  --module org/azure/object-repo \
  --inputs "$HYOPS_CORE_ROOT/modules/org/azure/object-repo/examples/inputs.min.yml"
```

Fetch account key out-of-band:

```bash
az storage account keys list \
  --resource-group <resource_group_name> \
  --account-name <storage_account_name> \
  --query '[0].value' -o tsv
```
