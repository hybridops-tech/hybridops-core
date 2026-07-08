# Blueprints

Blueprints are product orchestration manifests for supported module chains.

They package repeatable outcomes, not implementation details.

## Operating Modes
- `bootstrap`: Day-0 bring-up with minimal prerequisites.
- `authoritative`: Day-1+ operation where NetBox-backed IPAM/inventory is authoritative.
- `hybrid`: mixed bootstrap + authoritative flow in one chain.

## Contract Model
- `intent`: module input intent is declared per step.
- `policy`: run behavior guardrails (`fail_fast`, `evidence_required`, `ipam_authority`, `netbox_live_api_check`).
- `contracts`: per-step delivery contracts (`addressing_mode`, required upstream state).
- `verification`: probes remain module-level and run records remain deterministic.

`netbox_live_api_check` notes:
- Default: `false` (state-based NetBox authority gate only).
- When `true`, blueprint preflight/deploy also probes live NetBox API reachability and token validity for steps that require NetBox authority/IPAM.
- Use this in environments where strict API liveness should block execution early.

## Reference Blueprints

Each shipped blueprint directory contains a `blueprint.yml` contract and a local `README.md`.

### On-prem

| Blueprint | Outcome |
|---|---|
| [`onprem/bootstrap-netbox@v1`](onprem/bootstrap-netbox@v1) | SDN, template image, pgcore, and NetBox bootstrap. |
| [`onprem/authoritative-foundation@v1`](onprem/authoritative-foundation@v1) | NetBox-backed IPAM foundation for later platform services. |
| [`onprem/netbox-ha-cutover@v1`](onprem/netbox-ha-cutover@v1) | Re-point NetBox from bootstrap pgcore to PostgreSQL HA. |
| [`onprem/postgresql-ha@v1`](onprem/postgresql-ha@v1) | Patroni + etcd PostgreSQL HA on the on-prem foundation. |
| [`onprem/rke2@v1`](onprem/rke2@v1) | On-prem RKE2 cluster with exported kubeconfig. |
| [`onprem/rke2-workloads@v1`](onprem/rke2-workloads@v1) | RKE2 plus Argo CD root app and GSM bootstrap secret. |
| [`onprem/eve-ng@v1`](onprem/eve-ng@v1) | Proxmox-hosted EVE-NG training and network simulation platform. |

### GCP

| Blueprint | Outcome |
|---|---|
| [`gcp/gke-burst@v1`](gcp/gke-burst@v1) | GKE burst cluster with kubeconfig, Argo CD, and GCP Secret Manager store. |
| [`gcp/linux-desktop@v1`](gcp/linux-desktop@v1) | Ubuntu desktop VM with XFCE and XRDP. |
| [`gcp/windows-desktop@v1`](gcp/windows-desktop@v1) | Windows Server VM with scoped RDP access. |
| [`gcp/eve-ng@v1`](gcp/eve-ng@v1) | Private nested-virtualization-capable EVE-NG host on GCP. |

### Networking

| Blueprint | Outcome |
|---|---|
| [`networking/hetzner-vyos-edge@v1`](networking/hetzner-vyos-edge@v1) | Hetzner VyOS routed edge pair. |
| [`networking/onprem-vyos-edge@v1`](networking/onprem-vyos-edge@v1) | Proxmox-hosted VyOS edge appliance. |
| [`networking/wan-hub-edge@v1`](networking/wan-hub-edge@v1) | GCP hub, Hetzner edge, HA VPN, and BGP. |
| [`networking/onprem-site-extension@v1`](networking/onprem-site-extension@v1) | Dual-tunnel site extension between on-prem and edge. |
| [`networking/edge-control-plane@v1`](networking/edge-control-plane@v1) | WAN, observability, DNS intent, and decision-control services. |
| [`networking/gcp-ops-runner@v1`](networking/gcp-ops-runner@v1) | Private GCP runner for runner-local DR and burst execution. |
| [`networking/onprem-ops-runner@v1`](networking/onprem-ops-runner@v1) | On-prem runner for failback and local platform operations. |
| [`networking/powerdns-shared-primary@v1`](networking/powerdns-shared-primary@v1) | Writable internal DNS authority on the shared control host. |
| [`networking/powerdns-onprem-secondary@v1`](networking/powerdns-onprem-secondary@v1) | On-prem secondary DNS for local resolution resilience. |

### Disaster recovery

| Blueprint | Outcome |
|---|---|
| [`dr/postgresql-ha-backup-gcp@v1`](dr/postgresql-ha-backup-gcp@v1) | GCS-backed pgBackRest backup configuration. |
| [`dr/postgresql-ha-failover-gcp@v1`](dr/postgresql-ha-failover-gcp@v1) | Restore PostgreSQL HA into GCP from pgBackRest. |
| [`dr/postgresql-ha-failback-onprem@v1`](dr/postgresql-ha-failback-onprem@v1) | Restore PostgreSQL HA back on-prem from backups. |
| [`dr/postgresql-cloudsql-standby-gcp@v1`](dr/postgresql-cloudsql-standby-gcp@v1) | Managed Cloud SQL standby without traffic cutover. |
| [`dr/postgresql-cloudsql-promote-gcp@v1`](dr/postgresql-cloudsql-promote-gcp@v1) | Explicit Cloud SQL promotion gate and DNS cutover. |
| [`dr/postgresql-cloudsql-failback-onprem@v1`](dr/postgresql-cloudsql-failback-onprem@v1) | Explicit managed-cloud failback gate and DNS cutback. |

## CLI Usage
- Validate:
  - `hyops blueprint validate --ref onprem/bootstrap-netbox@v1 --blueprints-root blueprints`
- Preflight:
  - `hyops blueprint preflight --ref onprem/authoritative-foundation@v1 --blueprints-root blueprints --root /tmp/hyops-runtime`
- Plan:
  - `hyops blueprint plan --ref onprem/authoritative-foundation@v1 --blueprints-root blueprints`
- Deploy (execute):
  - `hyops blueprint deploy --ref onprem/authoritative-foundation@v1 --blueprints-root blueprints --execute`
- Deploy with explicit runtime root:
  - `hyops blueprint deploy --ref onprem/authoritative-foundation@v1 --blueprints-root blueprints --execute --root /tmp/hyops-runtime`

## Shipped Blueprint Boundary

Shipped blueprints must stay neutral and reusable.

Use public blueprints for:
- repeatable infrastructure delivery
- reusable DR primitives
- neutral traffic cutover chains
- generic GitOps bootstrap patterns

Keep private or operator specific composition out of the shipped blueprint surface when it:
- hardcodes one business application lane
- assumes one private repo layout or target name
- only makes sense for HybridOps-operated delivery

That application-specific composition should live in the selected workloads repo
and its managed target paths, with Core consuming it through generic repo and
target inputs instead of encoding the business lane into the blueprint name or contract.
