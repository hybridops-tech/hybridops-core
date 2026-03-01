# platform/onprem/postgresql-dr-source

Assess an on-prem PostgreSQL HA cluster and publish a normalized source contract for managed DR or controlled export workflows.

This module is intentionally non-destructive:

- it consumes existing PostgreSQL HA state
- it assesses the current primary/leader posture
- it publishes a source contract for downstream managed DR modules
- it does not cut over traffic
- it does not provision any cloud resources

## Recommended use

Use this after `platform/onprem/postgresql-ha` is healthy and before any managed DR target workflow.

Preferred state-driven composition:

- `inventory_state_ref=platform/onprem/postgresql-ha`
- `db_state_ref=platform/onprem/postgresql-ha`

## Usage

```bash
hyops preflight --env <env> --strict \
  --module platform/onprem/postgresql-dr-source \
  --inputs "$HYOPS_CORE_ROOT/modules/platform/onprem/postgresql-dr-source/examples/inputs.min.yml"

hyops apply --env <env> \
  --module platform/onprem/postgresql-dr-source \
  --inputs "$HYOPS_CORE_ROOT/modules/platform/onprem/postgresql-dr-source/examples/inputs.min.yml"
```

## Inputs

Key inputs:

- `dr_mode`
  - `managed-cloudsql`
  - `export`
- `inventory_state_ref`
- `db_state_ref`
- `allowed_consumer_cidrs`

## Outputs

- `source`
- `source_host`
- `source_port`
- `source_leader_name`
- `source_leader_host`
- `source_export_ready`
- `source_replication_candidate`
- `cap.db.postgresql_dr_source`

## Notes

- For `managed-cloudsql`, the module requires a minimum replication posture on the source leader and fails clearly if it is absent.
- `db_*` outputs are preserved from the selected application contract to support export-driven DR paths.
- This module is the source-side building block for the managed DR lane; it does not replace the existing backup/restore DR path.
