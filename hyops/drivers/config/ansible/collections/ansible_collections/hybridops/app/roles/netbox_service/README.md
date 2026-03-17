# netbox_service

Deploy NetBox on a Linux VM using Docker Compose.

This role renders and runs a Docker Compose project (NetBox web + worker + housekeeping + Redis), configured to use an **external PostgreSQL** database tier.

## Architecture alignment

This role is the NetBox service runtime building block in the HybridOps bootstrap flow:

- [ADR-0002 — Source of Truth: NetBox-Driven Inventory](https://docs.hybridops.tech/adr/ADR-0002-source-of-truth-netbox-driven-inventory/) — bring NetBox up, seed it, then pivot automation to NetBox-backed inventories.
- [ADR-0501 — PostgreSQL on dedicated VM with DR replication](https://docs.hybridops.tech/adr/ADR-0501-postgresql-on-dedicated-vm-with-dr-replication/) — NetBox consumes an external PostgreSQL tier outside Kubernetes.
- [ADR-0020 — Secrets Strategy](https://docs.hybridops.tech/adr/ADR-0020-secrets-strategy-akv-now-sops-fallback-vault-later/) and [ADR-0502 — ESO + AKV](https://docs.hybridops.tech/adr/ADR-0502-external-secrets-operator-akv/) — secret values are supplied by the caller; this role does not mint secrets.

> ADR references are specific to HybridOps. The role remains usable as a general-purpose NetBox Compose deployer.

## Purpose and scope

### Included

- Render Compose assets:
  - `docker-compose.yml`
  - `netbox.env`
  - `configuration.py` (NetBox settings module)
- Run the Compose stack using the Docker Compose plugin.
- Optional dependency install: call `hybridops.common.docker_engine` when enabled.
- Preflight checks (Docker/Compose present, DB reachable when required, host-port conflict reporting/fail-fast).
- Optional bootstrap of a NetBox superuser (when password is supplied).

### Excluded

- PostgreSQL provisioning (use `hybridops.common.postgresql_service` or an equivalent DB role).
- NetBox “source-of-truth” seeding (use a separate `netbox_seed` role or platform seed playbook).
- Firewall/routing enforcement (enforce elsewhere; this role only binds a host port).
- HA/load-balancing, DR, backups, or upgrade orchestration (layer separately).

## Dependencies

- Docker Engine and Docker Compose plugin on the target host.
  - If `netbox_service_install_docker_engine: true`, this role installs the Docker baseline via `hybridops.common.docker_engine`.
- External PostgreSQL reachable from the NetBox host (when `netbox_service_require_db: true`).

## Requirements

- Ansible 2.14+
- Linux VM capable of running Docker Engine
- Outbound network access to pull container images (or a local registry mirror)

## Variables

### Core

- `netbox_service_smoke_only` (default: `false`)
  When `true`, performs validation and stops before rendering/running the stack.

- `netbox_service_install_docker_engine` (default: `true`)
  When `true`, calls `hybridops.common.docker_engine` before deployment.

- `netbox_service_version` (default: `v4.1.7`)
  Container tag for `netboxcommunity/netbox`.

- `netbox_service_install_root` (default: `/opt/netbox`)
  Root for Compose files and config templates.

- `netbox_service_data_root` (default: `/var/lib/netbox`)
  Persistent data root for media/reports/scripts/redis AOF.

- `netbox_service_compose_project` (default: `netbox`)
  Compose project name used for container naming and isolation.

- `netbox_service_http_host_port` (default: `8000`)
  Host port mapped to NetBox container port `8080`.

### PostgreSQL (required for real deploy)

- `netbox_service_require_db` (default: `true`)
  If `true`, preflight fails when PostgreSQL is unreachable.

- `netbox_service_db_host` (required when `netbox_service_require_db: true`)
- `netbox_service_db_port` (default: `5432`)
- `netbox_service_db_name` (default: `netbox`)
- `netbox_service_db_user` (default: `netbox`)
- `netbox_service_db_password` (required when `netbox_service_require_db: true`)

### Redis (Compose-local by default)

- `netbox_service_redis_host` (default: `redis`)
- `netbox_service_redis_port` (default: `6379`)
- `netbox_service_redis_password` (default: empty)

### App configuration

- `netbox_service_secret_key` (required for real deploy)
  Django SECRET_KEY. Provide via a secrets feed (Vault, env, Key Vault sync, etc.).

- `netbox_service_allowed_hosts` (default derives from hostname/domain)
  Used to set NetBox `ALLOWED_HOSTS`.

- `netbox_service_base_url` (default: empty string)
  Used to set NetBox base path.

### Superuser bootstrap (optional)

- `netbox_service_superuser_name` (default: `admin`)
- `netbox_service_superuser_email` (default: `admin@example.invalid`)
- `netbox_service_superuser_password` (default: empty)
  When set, the role runs `createsuperuser --no-input` via `docker compose exec` and environment variables.

### Preflight behaviour

- `netbox_service_preflight_port_conflict_policy` (default: `warn`)
  Values: `fail`, `warn`, `ignore`.

- `netbox_service_db_connect_timeout` (default: `3`)
  Timeout (seconds) for DB reachability check.

- `netbox_service_readiness_retries` (default: `80`)
- `netbox_service_readiness_delay` (default: `3`)
  Readiness budget for first-run API bootstrap on a clean database.

Legacy unprefixed `netbox_*` variables remain accepted as compatibility aliases.

## Usage

### Minimal playbook

```yaml
- name: NetBox service
  hosts: netbox
  become: true
  roles:
    - role: hybridops.app.netbox_service
```

### Example vars for a real deploy

Keep secrets out of Git. One workable pattern is:

- `deployment/inventories/core/group_vars/netbox.yml` contains non-secret values.
- `control/secrets.vault.env` (or equivalent) provides secret env vars sourced from your vault.

Example `group_vars/netbox.yml`:

```yaml
netbox_service_smoke_only: false
netbox_service_install_docker_engine: true

netbox_service_version: "v4.1.7"
netbox_service_http_host_port: 8000

netbox_service_db_host: "10.12.0.10"
netbox_service_db_port: 5432
netbox_service_db_name: "netbox"
netbox_service_db_user: "netbox"

netbox_service_db_password: "{{ lookup('env', 'NETBOX_DB_PASSWORD') }}"
netbox_service_secret_key: "{{ lookup('env', 'NETBOX_SECRET_KEY') }}"

netbox_service_superuser_password: "{{ lookup('env', 'NETBOX_SUPERUSER_PASSWORD') | default('', true) }}"
```

## What “seeding” means

Seeding is the step where NetBox is populated with your initial platform model (sites, prefixes, VLANs, VMs, primary IPs, tags/roles). In HybridOps, seeding is a separate concern:

1. Bring up PostgreSQL.
2. Deploy NetBox (this role).
3. Seed NetBox from exported infra state (CSV/JSON), then pivot Ansible to dynamic inventories.

## Troubleshooting quick checks

On the NetBox host:

```bash
cd /opt/netbox/compose
sudo docker compose --env-file netbox.env ps
sudo docker logs --tail=200 netbox-netbox-1
curl -I --max-time 3 http://127.0.0.1:8000/api/ || true
```

Common causes of failed readiness:

- DB not reachable from the NetBox host (`netbox_service_db_host:netbox_service_db_port`).
- Missing/incorrect `netbox_service_secret_key` or DB credentials.
- Incorrect configuration module mapping (volume and `NETBOX_CONFIGURATION` must match the container image expectations).
- First bootstrap on a clean database exceeded the configured readiness window.

Worker/housekeeping start behavior:

- The Compose template gates worker and housekeeping on a healthy NetBox web service so background containers do not race the initial schema migration.
- `netbox-housekeeping` is treated as a one-shot maintenance task and uses `restart: on-failure`, so a successful housekeeping pass does not loop forever in Compose.

## License

- Code: [MIT-0](https://spdx.org/licenses/MIT-0.html)  
- Documentation & diagrams: [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/)

See the [HybridOps licensing overview](https://docs.hybridops.tech/briefings/legal/licensing/)
for project-wide licence details, including branding and trademark notes.
