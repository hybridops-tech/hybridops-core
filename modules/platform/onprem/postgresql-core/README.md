# platform/onprem/postgresql-core

Configure PostgreSQL on an existing Linux host via Ansible.

This module is capability-style: it **does not provision a VM**. Pair it with `platform/onprem/platform-vm` (or another VM module) in a blueprint.

## Usage

```bash
# Provide NETBOX_DB_PASSWORD via shell env or runtime vault env
NETBOX_DB_PASSWORD='...' \
hyops apply --env dev \
  --module platform/onprem/postgresql-core \
  --inputs modules/platform/onprem/postgresql-core/examples/inputs.typical.yml
```

## Inputs

- `target_host` (required): SSH target IP/DNS.
- `target_user`, `target_port`, `ssh_private_key_file`: SSH connection.
- `pg_port`, `listen_addresses`, `allowed_clients`: PostgreSQL network policy.
- `db_name`, `db_user`, `db_password_env`: initial database/user bootstrap.

Secrets are read from environment variables (optionally from runtime vault env):

- `NETBOX_DB_PASSWORD` (default)

## Outputs

Published module state keys:

- `db_host`, `db_port`, `db_name`, `db_user`
- `db_password_env` (env-var name only; not the secret value)
- `cap.db.pgcore = ready`
