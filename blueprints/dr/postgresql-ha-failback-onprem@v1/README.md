# PostgreSQL HA DR Failback to On-Prem

Restore a Patroni and etcd PostgreSQL HA cluster on-prem from pgBackRest after a cloud failover lane has been used.

Outcome: on-prem PostgreSQL HA is restored from backups and publishes standard database connection outputs.

## Chain

```text
core/onprem/template-image
  -> platform/onprem/platform-vm
  -> platform/postgresql-ha
  -> platform/postgresql-ha-backup
  -> platform/network/dns-routing
  -> platform/network/dns-routing
```

See [blueprint.yml](blueprint.yml) for the full contract.

## Usage

```bash
hyops blueprint validate --ref dr/postgresql-ha-failback-onprem@v1 --blueprints-root blueprints
hyops blueprint preflight --env dev --ref dr/postgresql-ha-failback-onprem@v1 --blueprints-root blueprints
hyops blueprint deploy --env dev --ref dr/postgresql-ha-failback-onprem@v1 --blueprints-root blueprints --execute
```
