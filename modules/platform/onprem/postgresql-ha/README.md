# platform/onprem/postgresql-ha

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
- By default `inputs.restore_delta=false` (safer). If you set `restore_delta=true`, pgBackRest can overwrite an existing data directory.

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

Use `execution_plane` to declare where HyOps is expected to run from:

- `workstation-direct` (default): operator shell/laptop with direct reachability
- `runner-local`: shared runner in or near the target environment

Cloud DR blueprints should prefer `execution_plane: runner-local` so preflight and evidence reflect the intended pipeline-driven operating model.

## Inputs (high level)

- `cluster_vip` (recommended): stable client endpoint; if unset, outputs default to the master host IP.
- `allowed_clients`: explicit `pg_hba` allowlist; avoid broad networks.
- `apps`: multi-service DB contract (authoritative when non-empty).
- `patroni_cluster_name`, `postgresql_version`, `postgresql_port`, `dcs_type`, `dcs_exists`.

## Outputs

Published module state keys:

- `pg_host`, `pg_port`, `cluster_vip`
- `apps` (per-app connection details, including `db_password_env` env-var names only)
- Backward-compat: `db_host`, `db_port`, `db_name`, `db_user`, `db_password_env` from `apps.netbox` when present
- `cap.db.postgresql_ha = ready`
