# org/gcp/pgbackrest-repo

Provision a GCS bucket and a dedicated service account to be used as a pgBackRest repository backend.

This module is intentionally infra-only:

- It creates the bucket and IAM bindings.
- It does **not** create service account keys (to avoid storing secrets in Terraform state).
- It does **not** configure PostgreSQL or pgBackRest itself (use `platform/postgresql-ha-backup`).

For generic object storage use-cases (artifacts, logs, non-PostgreSQL backups), prefer `org/gcp/object-repo`. This module keeps pgBackRest-oriented defaults.

## Normalized outputs

This module now publishes a cross-provider contract:

- `repo_backend` (`gcs`)
- `repo_provider` (`gcp`)
- `repo_bucket_name`
- `repo_region`
- `repo_principal_type` (`service_account`)
- `repo_principal_name` (service account email)
- `repo_credential_create_hint`

Legacy aliases are still published: `bucket_name`, `service_account_email`, `gcloud_sa_key_hint`.

## Why no service account key creation?

Creating a service account key in Terraform would store the key material in state and logs.

HybridOps expects operators to generate the key out-of-band (or use an enterprise identity flow),
then store it into the HybridOps runtime vault for DR/CI/bootstrap usage (example env key: `PG_BACKUP_GCS_SA_JSON`).

## Example

Preferred when HybridOps already manages the target GCP project in the same env:

```bash
HYOPS_INPUT_project_state_ref=org/gcp/project-factory \
HYOPS_INPUT_bucket_name=hyops-pgbackrest-dev \
hyops apply --env dev \
  --module org/gcp/pgbackrest-repo \
  --inputs modules/org/gcp/pgbackrest-repo/examples/inputs.min.yml
```

Fallback for an external/pre-existing project:

1. Apply infra:

```bash
hyops preflight --env dev --strict \
  --module org/gcp/pgbackrest-repo \
  --inputs modules/org/gcp/pgbackrest-repo/examples/inputs.min.yml

hyops apply --env dev \
  --module org/gcp/pgbackrest-repo \
  --inputs modules/org/gcp/pgbackrest-repo/examples/inputs.min.yml
```

For the fallback path, set `project_id` and `bucket_name` in the input file first.

When `project_state_ref` is set, HybridOps resolves `project_id` from upstream state and treats it as authoritative for the run. `hyops init gcp` still provides runtime credentials and Terragrunt defaults, but it is not the preferred source of project intent for reusable module composition.

Bucket naming guidance:

- Recommended pattern: `hyops-<env>-pgbackrest-<suffix>`
- Example: `hyops-dev-pgbackrest-a1`
- Keep it lowercase and globally unique within GCS.

State-slot safety:

- A bucket name is treated as immutable within a given HybridOps state slot.
- If a state slot already points to one bucket, HybridOps will refuse to pivot that same slot to a different bucket name.
- To create a second repo, use a new `--state-instance`.

2. Create a service account key (example using gcloud):

```bash
# Replace email with module output "repo_principal_name"
gcloud iam service-accounts keys create ./pgbackrest-gcs-sa.json \
  --iam-account "<repo_principal_name>"
```

3. Store it into the runtime vault bundle:

```bash
export PG_BACKUP_GCS_SA_JSON="$(cat ./pgbackrest-gcs-sa.json)"
hyops secrets set --env dev --from-env PG_BACKUP_GCS_SA_JSON
```

4. Configure PostgreSQL HA backups to GCS:

```bash
hyops apply --env dev \
  --module platform/postgresql-ha-backup \
  --inputs modules/platform/postgresql-ha-backup/examples/inputs.gcs.yml
```
