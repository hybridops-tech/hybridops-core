# platform/postgresql-ha-backup

Configure pgBackRest backups (S3, GCS, or Azure Blob repo) for an existing Patroni PostgreSQL HA cluster.

Legacy compatibility ref `platform/onprem/postgresql-ha-backup` remains supported for existing state and automation, but new blueprints and docs should use `platform/postgresql-ha-backup`.

## What this module does

- Installs and configures `pgbackrest` on the Postgres cluster nodes (via `vitabaks.autobase`).
- Configures WAL archiving to the pgBackRest repository (enables DR-grade PITR).
- Installs cron jobs (guarded to run backups only on the primary node).
- Publishes module state outputs describing backup readiness.
- Supports optional `repo2` configuration (`secondary_enabled=true`) for secondary backup copy to another backend/cloud.

## What this module does not do

- Does not provision VMs.
- Does not deploy Patroni/etcd (use `platform/postgresql-ha` first).
- Does not create object-store resources (bring your own S3 bucket, GCS bucket, or Azure storage account/container).

## Prerequisites

- `platform/postgresql-ha` applied and `status=ok`.
- Inventory available (typically from `platform/onprem/platform-vm` state).
- When using state-driven inventory, default policy enforces NetBox-IPAM provenance
  (`inventory_requires_ipam=true`).
- Runtime vault decrypt works.
- Backup repository reachable from the Postgres nodes (HTTPS).

## Execution plane

Use `execution_plane` to declare where HyOps is expected to run from:

- `workstation-direct` (default): operator shell/laptop with direct reachability
- `runner-local`: shared runner in or near the target environment

Cloud DR backup/reconfigure steps should prefer `execution_plane: runner-local` so preflight fails with runner-oriented guidance instead of assuming workstation reachability.

## Repository input modes

You can configure repository settings in one of two ways:

- Explicit backend fields in inputs (`backend` + `s3_bucket`/`gcs_bucket`/`azure_*`).
- State-driven resolution via `repo_state_ref` (recommended), pointing to:
  - `org/aws/object-repo`
  - `org/gcp/object-repo`
  - `org/azure/object-repo`

Compatibility wrappers remain valid when already in use:

- `org/aws/pgbackrest-repo`
- `org/gcp/pgbackrest-repo`
- `org/azure/pgbackrest-repo`

When `repo_state_ref` is set, backend + repository location fields are derived from upstream state and treated as authoritative.

### Optional secondary repository (repo2)

To improve backup durability across clouds without running dual read-only databases:

- Enable: `secondary_enabled: true`
- Configure secondary backend via either:
  - explicit `secondary_backend` + `secondary_*` fields, or
  - `secondary_repo_state_ref` (recommended).

This configures pgBackRest `repo2-*` options. Scheduled and on-demand backups run for both repo1 and repo2 when enabled.

### Handling stale repo metadata on cluster rebuilds

When a new PostgreSQL cluster reuses an existing pgBackRest repo path, stanza metadata can
point to the old PostgreSQL system-id and cause apply failures.

- Default behavior: `repo_mismatch_action: fail` (safe, non-destructive)
- Optional recovery: `repo_mismatch_action: reset` (runs `stanza-delete --force` then re-creates stanza)

Use `reset` only when you explicitly want to re-initialize stanza metadata for that repository path.

## Secrets

This module expects the following secrets in the environment or runtime vault bundle.

Backend `s3` (AWS S3 or S3-compatible):

- `PG_BACKUP_S3_ACCESS_KEY_ID`
- `PG_BACKUP_S3_SECRET_ACCESS_KEY`

Backend `gcs` (Google Cloud Storage):

- `PG_BACKUP_GCS_SA_JSON` (service account JSON content)

Backend `azure` (Azure Blob Storage):

- `PG_BACKUP_AZURE_ACCOUNT_KEY` (storage account key)

Secondary backend credential env keys are independent by default:

- Secondary S3: `PG_BACKUP_SECONDARY_S3_ACCESS_KEY_ID`, `PG_BACKUP_SECONDARY_S3_SECRET_ACCESS_KEY`
- Secondary GCS: `PG_BACKUP_SECONDARY_GCS_SA_JSON`
- Secondary Azure: `PG_BACKUP_SECONDARY_AZURE_ACCOUNT_KEY`

## Examples

S3-compatible (MinIO):

- `examples/inputs.minio.yml`

GCS:

- `examples/inputs.gcs.yml`
- `examples/inputs.gcs.ha-state.yml` (consume current `platform/postgresql-ha` state directly)
- `examples/inputs.gcs.explicit-inventory.yml` (state-independent inventory mode)

Azure Blob:

- `examples/inputs.azure.yml`

Primary GCS + secondary Azure copy:

- `examples/inputs.gcs.azure-secondary.yml`

## Usage

Configure backups:

```bash
hyops preflight --env <env> --strict \
  --module platform/postgresql-ha-backup \
  --inputs modules/platform/postgresql-ha-backup/examples/inputs.minio.yml

hyops apply --env <env> \
  --module platform/postgresql-ha-backup \
  --inputs modules/platform/postgresql-ha-backup/examples/inputs.minio.yml
```

Example (explicit inventory_groups, no inventory_state_ref dependency):

```bash
hyops apply --env <env> \
  --module platform/postgresql-ha-backup \
  --inputs modules/platform/postgresql-ha-backup/examples/inputs.gcs.explicit-inventory.yml
```

Example (state-driven repository settings):

```bash
HYOPS_INPUT_repo_state_ref=org/gcp/object-repo \
hyops apply --env <env> \
  --module platform/postgresql-ha-backup \
  --inputs modules/platform/postgresql-ha-backup/examples/inputs.gcs.yml
```

Example (consume current PostgreSQL HA state, no explicit host IPs):

```bash
hyops apply --env <env> \
  --module platform/postgresql-ha-backup \
  --inputs modules/platform/postgresql-ha-backup/examples/inputs.gcs.ha-state.yml
```

Example (state-driven primary + secondary repositories):

```bash
HYOPS_INPUT_repo_state_ref=org/gcp/object-repo \
HYOPS_INPUT_secondary_enabled=true \
HYOPS_INPUT_secondary_repo_state_ref=org/azure/object-repo \
hyops apply --env <env> \
  --module platform/postgresql-ha-backup \
  --inputs modules/platform/postgresql-ha-backup/examples/inputs.gcs.azure-secondary.yml
```

Trigger an on-demand full backup:

```bash
HYOPS_INPUT_repo_state_ref=org/gcp/object-repo \
HYOPS_INPUT_apply_mode=backup \
hyops apply --env <env> \
  --module platform/postgresql-ha-backup \
  --inputs modules/platform/postgresql-ha-backup/examples/inputs.gcs.ha-state.yml
```

If the repository path was reused from an older cluster and pgBackRest reports a
system-id mismatch, recover once with:

```bash
HYOPS_INPUT_repo_state_ref=org/gcp/object-repo \
HYOPS_INPUT_apply_mode=backup \
HYOPS_INPUT_repo_mismatch_action=reset \
hyops apply --env <env> \
  --module platform/postgresql-ha-backup \
  --inputs modules/platform/postgresql-ha-backup/examples/inputs.gcs.ha-state.yml
```

After that one-time reset, return to the normal command without
`repo_mismatch_action=reset`.

Destroy (best-effort):

```bash
hyops destroy --env <env> \
  --module platform/postgresql-ha-backup \
  --inputs modules/platform/postgresql-ha-backup/examples/inputs.minio.yml
```

Note: destroy currently disables the scheduled cron jobs, but does not attempt to remove archive configuration from a running Patroni cluster.
