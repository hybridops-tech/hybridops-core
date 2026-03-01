# platform/onprem/netbox-db-migrate

Perform an explicit **NetBox database migration** from a source PostgreSQL contract
(typically `platform/onprem/postgresql-core`) to a target PostgreSQL HA contract
(typically `platform/onprem/postgresql-ha`) using `pg_dump` / `pg_restore`.

This module is **migration-only**:

- It does **not** repoint NetBox to the target DB (use `onprem/netbox-ha-cutover@v1` after migration).
- It does **not** provision databases or VMs.
- It is intended for a controlled maintenance window.

## Why this exists

`onprem/netbox-ha-cutover@v1` is intentionally a switch-only blueprint. It repoints
NetBox to the HA DB contract but does not migrate the existing records from the
bootstrap `pgcore` database. This module provides that missing migration step.

## Usage (shared NetBox authority example)

```bash
# Explicit confirmations are required
HYOPS_INPUT_maintenance_confirm=true \
HYOPS_INPUT_migration_confirm=true \
hyops apply --env shared \
  --module platform/onprem/netbox-db-migrate \
  --inputs modules/platform/onprem/netbox-db-migrate/examples/inputs.min.yml
```

Then run cutover:

```bash
hyops blueprint deploy --env shared --ref onprem/netbox-ha-cutover@v1 --execute
```

## Safety model

- `maintenance_confirm=true` is required (operator acknowledges maintenance window)
- `migration_confirm=true` is required (operator acknowledges data move)
- `target_replace_confirm=false` by default
  - if the target DB already contains tables, the module fails fast
  - set `target_replace_confirm=true` only when you intentionally want to replace the target DB contents

## State-driven DB contracts (recommended)

Defaults assume the shared NetBox bootstrap path:

- source: `platform/onprem/postgresql-core`
- target: `platform/onprem/postgresql-ha`
- app key: `netbox`

Advanced:

- `source_db_state_env` / `target_db_state_env` allow controlled cross-env references
- explicit `source_db_*` / `target_db_*` values are supported, but state-driven contracts are preferred

## Outputs

Published module state keys:

- `migration` (source/target endpoints, dump path/hash, row-count checks)
- `cap.db.netbox_migration = ready`
