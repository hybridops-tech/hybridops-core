# platform/onprem/postgresql-dr-source

Assess an on-prem PostgreSQL HA cluster and publish a normalized source contract for managed DR or controlled export workflows.

This module is intentionally non-destructive:

- it consumes existing PostgreSQL HA state
- it assesses the current primary/leader posture
- it publishes a source contract for downstream managed DR modules
- it does not cut over traffic
- it does not provision any cloud resources

## Recommended use

Use this after `platform/postgresql-ha` is healthy and before any managed DR target workflow.

Preferred state-driven composition:

- `inventory_state_ref=platform/postgresql-ha`
- `db_state_ref=platform/postgresql-ha`

When more than one PostgreSQL HA state instance exists, point both refs at the
current authoritative instance instead of relying on a stale bare latest slot.
For example, after an on-prem failback drill, use
`platform/postgresql-ha#postgresql_restore_onprem_failback`.

`inventory_requires_ipam` defaults to `false` because this module only assesses
an existing HA lane. Turn it on only when you deliberately want provenance
enforcement from an upstream NetBox/IPAM-managed VM inventory contract.

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
- `source_replication_user`

When the managed standby lane reaches the source through a site-extension SNAT
path, `allowed_consumer_cidrs` should describe the effective translated source
that PostgreSQL will actually see, not a stale pre-NAT runner IP.

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

- For `managed-cloudsql`, the module requires a minimum logical-replication posture on the source leader and fails clearly if it is absent.
- `managed-cloudsql` also requires `pglogical` to be available on the source node, installed in the selected database, present in `shared_preload_libraries`, and usable by the replication user on schema `pglogical`.
- The intended upstream reconcile is `platform/postgresql-ha` (or `platform/onprem/postgresql-ha`) with:
  - `apply_mode=maintenance`
  - `pglogical_enable=true`
  - `pending_restart=true`
- `db_*` outputs are preserved from the selected application contract to support export-driven DR paths.
- This module is the source-side building block for the managed DR lane; it does not replace the existing backup/restore DR path.
