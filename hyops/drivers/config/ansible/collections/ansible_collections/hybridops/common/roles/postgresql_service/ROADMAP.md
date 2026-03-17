# purpose: Roadmap for PostgreSQL data tier and NetBox bring-up (platform backbone)
# adr: ADR-0101, ADR-0102, ADR-0103, ADR-0104
# maintainer: HybridOps.Tech

## Scope

This roadmap captures the next execution steps to move from a validated PostgreSQL wrapper role to a working NetBox deployment backed by the shared PostgreSQL data tier, aligned to the HybridOps.Tech network segmentation model.

This is an execution checklist, not a design document.

## Current status

### Completed

- CI control node can reach Linux templates via SSH key auth.
- Non-interactive privilege escalation validated:
  - `ssh <user>@<ip> 'sudo -n id'` succeeds.
- `hybridops.common.postgresql_service` converges successfully on a test host.
- `pg_hba.conf` allowlist generation works and matches `postgresql_service_allowed_clients`.
- PostgreSQL config is being applied (e.g., `listen_addresses` rendered into `postgresql.conf`).
- Evidence capture tasks produce:
  - `systemctl-status.txt`
  - `pg_isready.txt`
  - timestamp marker

### Known gap (expected)

- The test host currently only has management IP `10.10.x.x`. It does not have the Data VLAN IP (`10.12.x.x`), so PostgreSQL cannot bind to the data address even if configured.
- `pg_hba.conf` can be correct while the data-plane listener is absent. The binding requirement is network/interface/IP-level.

## Milestones

### Milestone 1 — Data VLAN is real on the pgcore VM

Outcome: the pgcore VM has a data-tier interface/IP and PostgreSQL is reachable only on the data-tier address.

Checklist:

- Attach a second NIC to the VM on the Data VLAN VNet (example: `vnetdata`).
- Assign the data-tier IP (example: `10.12.0.10/24`) via:
  - Proxmox cloud-init ipconfig (preferred), or
  - OS network configuration (secondary).
- Validate from pgcore VM:
  - `ip -br addr` shows `10.12.0.10/24` on a non-mgmt interface.
  - `ss -ltnp | grep :5432` shows listener on `10.12.0.10:5432`.
  - `sudo -u postgres psql -tAc "show listen_addresses;"` includes the data IP.

Notes:

- Do not expose PostgreSQL on the management IP for the production posture.
- If short-term validation is needed, temporarily bind to the mgmt IP on a test VM only, then revert.

### Milestone 2 — PostgreSQL service tier is production-aligned

Outcome: pgcore enforces least-privilege access and is ready for NetBox.

Checklist:

- Ensure `listen_addresses` includes:
  - `127.0.0.1`
  - `10.12.0.10` (pgcore data IP)
- Ensure `pg_hba.conf` includes:
  - localhost defaults
  - NetBox VM `/32`
  - RKE2 node `/32`s (or approved subnet range during early bring-up)
- Validate:
  - `HBA=$(sudo -u postgres psql -tAc "show hba_file;"); sudo sed -n '1,200p' "$HBA"'`
  - restart is clean: `sudo systemctl restart postgresql && sudo systemctl status postgresql --no-pager -l`

Secrets handling:

- Platform variables should define `netbox_db_password` using a vault-first + env fallback mapping.
- CI smoke tests should not depend on real secrets unless the CI runner injects them.

### Milestone 3 — NetBox VM is provisioned and reachable

Outcome: NetBox host exists with correct network placement and baseline connectivity.

Checklist:

- Provision NetBox VM (separate VM from pgcore).
- Attach:
  - mgmt interface (VLAN 10) for admin access
  - data interface (VLAN 12) if NetBox will reach DB via data-tier routing (recommended)
- Validate:
  - SSH access and `sudo -n` works.
  - DNS and routing allow reaching `10.12.0.10:5432`.

### Milestone 4 — NetBox deployed against external PostgreSQL

Outcome: NetBox uses pgcore as its DB backend.

Checklist (deployment-level):

- Ensure DB objects exist (by role or manual SQL):
  - database: `netbox`
  - role/user: `netbox`
  - privileges: owner or explicit grants as required
- Apply NetBox deployment (Docker on the VM or native systemd approach; keep consistent with your platform conventions).
- Configure NetBox:
  - `DB_HOST=10.12.0.10`
  - `DB_NAME=netbox`
  - `DB_USER=netbox`
  - `DB_PASSWORD=<from secret source>`
- Validate from NetBox VM:
  - `PGPASSWORD='<pw>' psql -h 10.12.0.10 -U netbox -d netbox -c "select 1;"`

Access control validation:

- Positive test:
  - From NetBox VM: connection succeeds.
- Negative test:
  - From a non-allowlisted VM: connection fails with `no pg_hba.conf entry` or auth failure.

### Milestone 5 — NetBox becomes IPAM SoT and feeds downstream automation

Outcome: NetBox is authoritative for prefixes and IP assignments; Terraform/Ansible consume it.

Checklist:

- Seed prefixes, VLANs, and IP ranges using your existing import scripts/workflows.
- Validate CRUD operations and API token handling.
- Integrate NetBox dynamic inventory (if applicable).
- Prove a downstream consumer reads from NetBox and allocates/attaches IPs consistently.

## Operational validation checklist

Run on pgcore:

- Service health:
  - `systemctl status postgresql --no-pager -l`
  - `pg_isready -h 127.0.0.1 -p 5432`
- Listener check:
  - `ss -ltnp | grep :5432`
- Effective config:
  - `sudo -u postgres psql -tAc "show listen_addresses;"`
  - `sudo -u postgres psql -tAc "show port;"`
  - `sudo -u postgres psql -tAc "show hba_file;"`

Run from NetBox VM:

- Connectivity:
  - `PGPASSWORD='<pw>' psql -h 10.12.0.10 -U netbox -d netbox -c "select 1;"`
- Client identity (helps confirm SNAT behaviour):
  - `PGPASSWORD='<pw>' psql -h 10.12.0.10 -U netbox -d netbox -c "select inet_client_addr();"`

Run from an unauthorised VM:

- Confirm denial:
  - same command should fail (expected).

## Evidence to capture

Minimum evidence for the platform backbone milestone:

- `ip -br addr` on pgcore showing mgmt + data IPs
- `ss -ltnp | grep :5432` showing bound listeners (127.0.0.1 + data IP)
- `show listen_addresses;` output
- `pg_hba.conf` excerpt showing allowlist rules
- NetBox-to-DB successful `select 1` output
- Unauthorised host failure output (pg_hba/auth failure)
- Role evidence directory outputs under `/var/lib/hybridops/evidence/postgresql`

## Next actions (recommended order)

1) Attach data VLAN NIC and configure `10.12.0.10` on pgcore VM.
2) Re-run `postgresql_service` against pgcore and verify listener binds to `10.12.0.10`.
3) Provision NetBox VM (mgmt + data) and validate routing to `10.12.0.10:5432`.
4) Deploy NetBox with external PostgreSQL.
5) Run positive and negative DB connectivity tests.
6) Seed NetBox IPAM and validate downstream consumption.
