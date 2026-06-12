# On-Prem NetBox DB Cutover to PostgreSQL HA

Re-apply NetBox so it consumes the PostgreSQL HA database contract from state instead of the bootstrap PostgreSQL core lane.

Outcome: NetBox uses `platform/postgresql-ha` outputs for `apps.netbox.db_*`.

## Chain

```text
platform/onprem/netbox
```

See [blueprint.yml](blueprint.yml) for the full contract.

## Usage

```bash
hyops blueprint validate --ref onprem/netbox-ha-cutover@v1 --blueprints-root blueprints
hyops blueprint preflight --env dev --ref onprem/netbox-ha-cutover@v1 --blueprints-root blueprints
hyops blueprint deploy --env dev --ref onprem/netbox-ha-cutover@v1 --blueprints-root blueprints --execute
```
