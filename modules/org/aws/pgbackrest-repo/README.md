# org/aws/pgbackrest-repo

Provision an S3 bucket and a dedicated IAM user for pgBackRest backup repositories.

This module is infra-only:

- Creates the S3 bucket with public access blocked and encryption enabled.
- Creates an IAM user with least-privilege bucket access.
- Does **not** create access keys (avoid secrets in Terraform state).

For generic object storage use-cases (artifacts, logs, non-PostgreSQL backups), prefer `org/aws/object-repo`. This module keeps pgBackRest-oriented defaults.

## Normalized outputs

This module now publishes a cross-provider contract:

- `repo_backend` (`s3`)
- `repo_provider` (`aws`)
- `repo_bucket_name`
- `repo_region`
- `repo_principal_type` (`iam_user`)
- `repo_principal_name` (IAM username)
- `repo_credential_create_hint`

Legacy aliases are still published: `bucket_name`, `aws_region`, `iam_user_name`, `access_key_hint`.

## Security model

Access keys are generated out-of-band and stored in the HyOps runtime vault.

Recommended flow:

1. Apply infra module.
2. Create IAM access key using AWS CLI.
3. Store key/secret in runtime vault (`PG_BACKUP_S3_ACCESS_KEY_ID`, `PG_BACKUP_S3_SECRET_ACCESS_KEY`).
4. Run `platform/onprem/postgresql-ha-backup` with `backend: s3`.

## Example

```bash
hyops preflight --env dev --strict \
  --module org/aws/pgbackrest-repo \
  --inputs "$HOME/.hybridops/core/app/modules/org/aws/pgbackrest-repo/examples/inputs.min.yml"

hyops apply --env dev \
  --module org/aws/pgbackrest-repo \
  --inputs "$HOME/.hybridops/core/app/modules/org/aws/pgbackrest-repo/examples/inputs.min.yml"
```

Then create access key (out-of-band):

```bash
# Use module output "repo_principal_name"
aws iam create-access-key --user-name <repo_principal_name>
```

Store into vault:

```bash
hyops secrets set --env dev \
  PG_BACKUP_S3_ACCESS_KEY_ID='...' \
  PG_BACKUP_S3_SECRET_ACCESS_KEY='...'
```
