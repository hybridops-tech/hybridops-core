# platform/onprem/netbox

Configure NetBox on an existing Linux host via Ansible (Docker Compose).

This module is capability-style: it **does not provision a VM**.

## Usage

```bash
NETBOX_DB_PASSWORD='...' \
NETBOX_SECRET_KEY='...' \
NETBOX_SUPERUSER_PASSWORD='...' \
NETBOX_API_TOKEN='...' \
hyops apply --env dev \
  --module platform/onprem/netbox \
  --inputs modules/platform/onprem/netbox/examples/inputs.typical.yml
```

## Inputs

- `target_host` (required): SSH target IP/DNS.
- `db_state_ref` (recommended): upstream DB module state ref (preferred: `platform/onprem/postgresql-ha`).
- `db_state_env` (optional): HyOps env name to resolve `db_state_ref` from (for example `dev` when running NetBox cutover in `shared`).
- `db_host`, `db_port`, `db_name`, `db_user` (fallback): external PostgreSQL connection when not using `db_state_ref`.
- `db_password_env`, `secret_key_env`: env-var names used to read secrets.
- `netbox_version`, `netbox_http_host_port`, `netbox_hostname`, `netbox_domain`
- `seed_foundation_netbox_sync` (optional): sync-only import of exported SDN/VM foundation datasets into NetBox after NetBox is online (bootstrap use-case)
- `seed_foundation_netbox_wait_s` (optional): controller-side API wait window before sync-only seed (default `60`)

Legacy rollback to `platform/onprem/postgresql-core` requires explicit opt-in:

- `db_state_ref: platform/onprem/postgresql-core`
- `allow_legacy_pgcore: true`

## Required Secrets

By default, secrets are supplied via environment variables (optionally from runtime vault env):

- `NETBOX_DB_PASSWORD`
- `NETBOX_SECRET_KEY`
- `NETBOX_SUPERUSER_PASSWORD`
- `NETBOX_API_TOKEN`

By default, apply treats `NETBOX_SUPERUSER_PASSWORD` as authoritative and reconciles
the existing `admin` user's password to this value (idempotent). This keeps
bootstrap/redeploy login credentials deterministic.

## Outputs

Published module state keys:

- `netbox_url`
- `netbox_api_url`
- `cap.ipam.netbox = ready`
