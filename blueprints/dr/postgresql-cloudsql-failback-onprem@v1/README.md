# PostgreSQL Managed DR Failback to On-Prem

Fail back a managed Cloud SQL DR lane to the on-prem PostgreSQL HA endpoint after the cloud primary has been fenced and the on-prem lane has been rebuilt or reseeded.

Outcome: application traffic is redirected back to the on-prem PostgreSQL HA endpoint after a controlled managed-cloud DR event.

## Chain

```text
core/shared/manual-gate
  -> platform/network/dns-routing
  -> platform/network/dns-routing
```

See [blueprint.yml](blueprint.yml) for the full contract.

## Usage

```bash
hyops blueprint validate --ref dr/postgresql-cloudsql-failback-onprem@v1 --blueprints-root blueprints
hyops blueprint preflight --env <env> --ref dr/postgresql-cloudsql-failback-onprem@v1 --blueprints-root blueprints
hyops blueprint deploy --env <env> --ref dr/postgresql-cloudsql-failback-onprem@v1 --blueprints-root blueprints --execute
```
