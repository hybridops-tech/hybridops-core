# PostgreSQL Managed DR Promote in GCP

Promote the managed Cloud SQL standby after explicit operator confirmation that the source has been fenced and promotion is approved.

Outcome: application traffic is redirected to the managed GCP PostgreSQL endpoint after promotion and source fencing are confirmed.

## Chain

```text
org/gcp/cloudsql-external-replica
  -> core/shared/manual-gate
  -> platform/network/dns-routing
  -> platform/network/dns-routing
```

See [blueprint.yml](blueprint.yml) for the full contract.

## Usage

```bash
hyops blueprint validate --ref dr/postgresql-cloudsql-promote-gcp@v1 --blueprints-root blueprints
hyops blueprint preflight --env <env> --ref dr/postgresql-cloudsql-promote-gcp@v1 --blueprints-root blueprints
hyops blueprint deploy --env <env> --ref dr/postgresql-cloudsql-promote-gcp@v1 --blueprints-root blueprints --execute
```
