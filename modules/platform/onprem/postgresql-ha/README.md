# platform/onprem/postgresql-ha

Legacy compatibility module ref. The canonical ref is `platform/postgresql-ha`.

Deploy a highly available PostgreSQL cluster (Patroni + etcd) on existing Linux hosts via Ansible (Autobase).

This module is capability-style: it **does not provision VMs**. Pair it with `platform/onprem/platform-vm` (or another VM module) in a blueprint.
When using state-driven inventory from `platform/onprem/platform-vm`, default policy enforces NetBox-IPAM provenance (`inventory_requires_ipam=true`).

Note: the Autobase inventory group `replica` refers to on-prem standby members in the same Patroni cluster. A cloud DR read-only replica is a separate concern (handled by a different module/blueprint).

## Usage

```bash
# Required secrets (can be loaded from runtime vault env with load_vault_env=true)
PATRONI_SUPERUSER_PASSWORD='...' \
PATRONI_REPLICATION_PASSWORD='...' \
NETBOX_DB_PASSWORD='...' \
hyops apply --env dev \
  --module platform/onprem/postgresql-ha \
  --inputs modules/platform/onprem/postgresql-ha/examples/inputs.min.yml
```

## Apply Modes

This module supports day-2 config reconcile via Autobase:

- `inputs.apply_mode=bootstrap`: initial cluster bootstrap (`vitabaks.autobase.deploy_pgcluster`)
- `inputs.apply_mode=maintenance`: reconcile/update config on an existing cluster (`vitabaks.autobase.config_pgcluster`)
- `inputs.apply_mode=restore`: bootstrap a new cluster from pgBackRest backups (DR/failback; uses `playbook.restore.yml`)
- `inputs.apply_mode=auto` (default): uses `maintenance` when prior module state is `ok`, otherwise `bootstrap`

Example (force maintenance):

```bash
HYOPS_INPUT_apply_mode=maintenance \
hyops apply --env dev --module platform/onprem/postgresql-ha \
  --inputs modules/platform/onprem/postgresql-ha/examples/inputs.min.yml
```

## Restore (DR / Failback)

`apply_mode=restore` bootstraps the Patroni cluster from a pgBackRest repository (S3 or GCS). This is intended for:

- Cloud failover (restore to fresh cloud VMs)
- On-prem failback (restore to fresh on-prem VMs)

This mode is intentionally guarded:

- You must set `inputs.restore_confirm=true`
- You must select the recovery source explicitly with one of:
  - `inputs.backup_state_ref`
  - `inputs.restore_set`
  - `inputs.restore_target_time`
- By default `inputs.restore_delta=false` (safer). If you set `restore_delta=true`, pgBackRest can overwrite an existing data directory.
- When the repository contains divergent timelines from earlier drills/promotions, prefer pinning:
  - `inputs.restore_set`
  - `inputs.restore_target_timeline`
  - and optionally `inputs.restore_target_time` for PITR
- Instead of inspecting pgBackRest manually, you can point restore at a backup-run
  module state and let HybridOps resolve the backup label:
  - `inputs.backup_state_ref`
  - `inputs.backup_state_env` (optional)
  - `inputs.allow_cross_env_state=true` when `backup_state_env` points to a non-`shared` env for a controlled drill or migration
- Keep `inputs.restore_target_timeline` explicit when you need to pin a specific
  recovery timeline.

Typical workflow:

1. Deploy the primary HA cluster with `platform/onprem/postgresql-ha`
2. Configure backups + WAL archiving with `platform/onprem/postgresql-ha-backup`
3. Trigger an on-demand backup:

```bash
HYOPS_INPUT_apply_mode=backup \
hyops apply --env dev \
  --module platform/onprem/postgresql-ha-backup \
  --inputs modules/platform/onprem/postgresql-ha-backup/examples/inputs.gcs.yml
```

4. Restore to a fresh target cluster (inventory can come from a VM module state or explicit inventory_groups):

```bash
HYOPS_INPUT_apply_mode=restore \
HYOPS_INPUT_restore_confirm=true \
hyops apply --env dev \
  --module platform/onprem/postgresql-ha \
  --inputs modules/platform/onprem/postgresql-ha/examples/inputs.restore.gcs.yml
```

If you have a recent backup-run state, prefer consuming it directly:

```bash
HYOPS_INPUT_apply_mode=restore \
HYOPS_INPUT_restore_confirm=true \
HYOPS_INPUT_backup_state_ref=platform/onprem/postgresql-ha-backup#postgresql_backup_run_onprem_app_proof_drill \
hyops apply --env drill \
  --module platform/onprem/postgresql-ha \
  --inputs modules/platform/onprem/postgresql-ha/examples/inputs.restore.gcs.yml
```

For isolated drills that restore from another env, add both:

- `HYOPS_INPUT_backup_state_env=<env>`
- `HYOPS_INPUT_allow_cross_env_state=true`

Same-env resolution is the default. `shared` is the only normal cross-env authority.

If pgBackRest reports a timeline mismatch or no backup-run state exists yet, inspect the repository first:

```bash
sudo -u postgres pgbackrest --stanza=postgres-ha info --output=json
```

Then rerun with an explicit backup set and target timeline, for example:

```bash
HYOPS_INPUT_apply_mode=restore \
HYOPS_INPUT_restore_confirm=true \
HYOPS_INPUT_restore_set=20260308-030002F \
HYOPS_INPUT_restore_target_timeline=7 \
hyops apply --env dev \
  --module platform/onprem/postgresql-ha \
  --inputs modules/platform/onprem/postgresql-ha/examples/inputs.restore.gcs.yml
```

Note: restore requires repository credentials in env/vault:

- S3: `PG_BACKUP_S3_ACCESS_KEY_ID`, `PG_BACKUP_S3_SECRET_ACCESS_KEY`
- GCS: `PG_BACKUP_GCS_SA_JSON` (service account JSON content)

Tip: include the relevant `PG_BACKUP_*` env-var keys in `inputs.required_env` so `hyops preflight --strict` fails fast when secrets are missing
(the `examples/inputs.restore.*.yml` overlays already do this).

## Inventory

Autobase expects these inventory groups:

- `master` (exactly 1 host)
- `replica` (1+ hosts)
- `postgres_cluster` (master + replicas)
- `etcd_cluster` (required when `dcs_type=etcd` and `dcs_exists=false`)

Prefer state-driven inventory:

- `inventory_state_ref: platform/onprem/platform-vm`
- `inventory_vm_groups: {group: [vm_key, ...]}`
- `inventory_requires_ipam: true` (default) requires upstream VM state contract:
  - `state.input_contract.addressing_mode=ipam`
  - `state.input_contract.ipam_provider=netbox`

## Execution plane

Use `execution_plane` to declare where HybridOps is expected to run from:

- `workstation-direct` (default): operator shell/laptop with direct reachability
- `runner-local`: shared runner in or near the target environment

Cloud DR blueprints should prefer `execution_plane: runner-local` so preflight and run records reflect the intended pipeline-driven operating model.

## Inputs (high level)

- `cluster_vip` (recommended): stable client endpoint; if unset, outputs default to the master host IP.
- `endpoint_dns_name` (recommended for DR): stable DNS name that applications should use across failover/failback. When set, outputs publish `endpoint_target=<dns name>` while `db_host`/`pg_host` continue to show the current active host or VIP.
- `allowed_clients`: explicit `pg_hba` allowlist; avoid broad networks.
- `apps`: multi-service DB contract (authoritative when non-empty).
- `netdata_install`: optional node-local Netdata install; defaults to `false` so DR/bootstrap is not blocked on monitoring package installs.
- `pending_restart`: explicit approval for controlled Patroni restart during maintenance when parameters require it.
- `pglogical_enable`: day-2 managed Cloud SQL source posture. Use only with `apply_mode=maintenance`.
- `pglogical_databases`: optional list of databases that must have the `pglogical` extension. When omitted, HybridOps uses the normalized application contract (for example `netbox`).
- `patroni_cluster_name`, `postgresql_version`, `postgresql_port`, `dcs_type`, `dcs_exists`.

## Managed Cloud SQL source posture

When the cluster is the source for `platform/onprem/postgresql-dr-source` in
`managed-cloudsql` mode, first reconcile the source HA lane with:

- `apply_mode=maintenance`
- `pglogical_enable=true`
- `pending_restart=true`

This maintenance run:

- installs the `pglogical` package on each PostgreSQL node
- appends `pglogical` to Patroni-managed `shared_preload_libraries`
- performs the controlled restart required for that parameter change
- ensures the `pglogical` extension exists in the selected application databases
- grants the replication user `USAGE` on schema `pglogical` in those databases

This is intentionally explicit because `shared_preload_libraries` changes are
restart-bearing and should not happen silently during normal HA reconciles.

## Outputs

Published module state keys:

- `pg_host`, `pg_port`, `cluster_vip`
- `endpoint_target`, `endpoint_target_type`, `endpoint_dns_name`, `endpoint_host`, `endpoint_port`, `endpoint_cutover_required`
- `apps` (per-app connection details, including `db_password_env` env-var names only)
- Backward-compat: `db_host`, `db_port`, `db_name`, `db_user`, `db_password_env` from `apps.netbox` when present
- `cap.db.postgresql_ha = ready`

Endpoint semantics:

- `endpoint_target`: what clients should be configured to use
- `endpoint_target_type`:
  - `dns` when `endpoint_dns_name` is set
  - `vip` when `cluster_vip` is set and no DNS name is set
  - `host` when neither DNS nor VIP is configured
- `endpoint_host`: current active data-plane address behind the endpoint; this is the VIP when configured, otherwise the resolved leader address used for direct host cutover
- `endpoint_cutover_required`:
  - `true` when clients are pinned to a raw host or when DNS must be updated during DR
  - `false` when a stable in-cluster VIP is already the client endpoint
