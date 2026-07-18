# PostgreSQL HA Backup to GCP

Create a GCS-backed object repository and wire an existing PostgreSQL HA cluster to pgBackRest backup state.

Outcome: the on-prem PostgreSQL HA cluster is configured for GCS-backed pgBackRest backups and publishes backup readiness outputs.

## Chain

```text
org/gcp/object-repo
  -> platform/postgresql-ha-backup
```

See [blueprint.yml](blueprint.yml) for the full contract.

## Usage

```bash
hyops blueprint validate --ref dr/postgresql-ha-backup-gcp@v1 --blueprints-root blueprints
hyops blueprint preflight --env <env> --ref dr/postgresql-ha-backup-gcp@v1 --blueprints-root blueprints
hyops blueprint deploy --env <env> --ref dr/postgresql-ha-backup-gcp@v1 --blueprints-root blueprints --execute
```
