# PostgreSQL Managed DR Standby in GCP

Establish a managed Cloud SQL external replication lane from the on-prem PostgreSQL source without cutting application traffic.

Outcome: a managed standby lane exists in GCP and publishes the same client-facing endpoint contract used by the self-managed PostgreSQL HA lane.

## Chain

```text
platform/onprem/postgresql-dr-source
  -> org/gcp/cloudsql-external-replica
  -> org/gcp/cloudsql-external-replica
```

See [blueprint.yml](blueprint.yml) for the full contract.

## Usage

```bash
hyops blueprint validate --ref dr/postgresql-cloudsql-standby-gcp@v1 --blueprints-root blueprints
hyops blueprint preflight --env <env> --ref dr/postgresql-cloudsql-standby-gcp@v1 --blueprints-root blueprints
hyops blueprint deploy --env <env> --ref dr/postgresql-cloudsql-standby-gcp@v1 --blueprints-root blueprints --execute
```
