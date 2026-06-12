# PostgreSQL HA DR Failover to GCP

Restore a Patroni and etcd PostgreSQL cluster into GCP from pgBackRest backups during a DR event or controlled drill.

Outcome: a new PostgreSQL primary is restored in GCP and publishes standard database connection outputs.

## Chain

```text
org/gcp/wan-cloud-nat
  -> platform/gcp/platform-vm
  -> platform/postgresql-ha
  -> platform/postgresql-ha-backup
  -> platform/network/dns-routing
  -> platform/network/dns-routing
```

See [blueprint.yml](blueprint.yml) for the full contract.

## Usage

```bash
hyops blueprint validate --ref dr/postgresql-ha-failover-gcp@v1 --blueprints-root blueprints
hyops blueprint preflight --env dev --ref dr/postgresql-ha-failover-gcp@v1 --blueprints-root blueprints
hyops blueprint deploy --env dev --ref dr/postgresql-ha-failover-gcp@v1 --blueprints-root blueprints --execute
```
