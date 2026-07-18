# On-Prem PostgreSQL HA

Build a Rocky 9 template if needed, provision PostgreSQL nodes, then deploy Patroni and etcd on the shared on-prem foundation.

Outcome: an HA PostgreSQL cluster is deployed and publishes connection outputs for downstream services.

## Chain

```text
core/onprem/template-image
  -> platform/onprem/platform-vm
  -> platform/postgresql-ha
```

See [blueprint.yml](blueprint.yml) for the full contract.

## Usage

```bash
hyops blueprint validate --ref onprem/postgresql-ha@v1 --blueprints-root blueprints
hyops blueprint preflight --env <env> --ref onprem/postgresql-ha@v1 --blueprints-root blueprints
hyops blueprint deploy --env <env> --ref onprem/postgresql-ha@v1 --blueprints-root blueprints --execute
```
