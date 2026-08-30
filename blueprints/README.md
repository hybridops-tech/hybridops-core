# Blueprints

In the command examples, replace `<env>` with the environment name used during
initialization.

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

### Completion boundary

A successful step proves only the lifecycle that its module or native controller
owns. It does not automatically prove that the blueprint's requested outcome is
ready for use.

For example, an infrastructure controller can finish provisioning a host while
the service or cluster role intended for that host is still not ready. The
controller's reported state remains authoritative for provisioning. If a later
system owns role readiness, represent that condition as a required downstream
step or module-owned probe instead of reinterpreting the provisioning state.

A blueprint is complete only after its required chain and the readiness or
verification checks declared by those modules succeed. This keeps the outer
operation boundary useful without creating a second control loop around the
native systems.

This distinction was clarified through the Contract Runtime review in
[#269](https://github.com/hybridops-tech/hybridops-core/issues/269) and the
resulting [Metal3 community discussion](https://groups.google.com/g/metal3-dev/c/pv9Is4TbQnI?pli=1).

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
| [`onprem/gns3@v1`](onprem/gns3@v1) | Private GNS3 server on a Proxmox-hosted Ubuntu VM. |

### GCP

| Blueprint | Outcome |
|---|---|
| [`gcp/gke-burst@v1`](gcp/gke-burst@v1) | GKE burst cluster with kubeconfig, Argo CD, and GCP Secret Manager store. |
| [`gcp/linux-desktop@v1`](gcp/linux-desktop@v1) | Ubuntu desktop VM with XFCE and XRDP. |
| [`gcp/windows-desktop@v1`](gcp/windows-desktop@v1) | Windows Server VM with scoped RDP access. |
| [`gcp/eve-ng@v1`](gcp/eve-ng@v1) | Private nested-virtualization-capable EVE-NG host on GCP. |
| [`gcp/gns3@v1`](gcp/gns3@v1) | Private nested-virtualization-capable GNS3 server on GCP. |

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

Inspect a blueprint locally before configuring a runtime or provider:

```bash
hyops blueprint validate --ref gcp/eve-ng@v1 --blueprints-root blueprints
hyops blueprint plan --ref gcp/eve-ng@v1 --blueprints-root blueprints
```

`validate` checks the manifest. `plan` validates it and prints the ordered
steps. Neither command selects a runtime, invokes a driver, or contacts the
provider.

Preflight is the next boundary. It resolves the runtime, module contracts,
credential requirements, state, and driver checks. Some paths may inspect live
state, but preflight does not deploy resources:

```bash
hyops blueprint preflight --env <env> \
  --ref gcp/eve-ng@v1 \
  --blueprints-root blueprints
```

After `init`, open a local overlay directly in your default editor:

```bash
hyops blueprint init --env <env> --ref gcp/eve-ng@v1 --edit
```

You can also run a separate edit step:

```bash
hyops blueprint edit --env <env> --ref gcp/eve-ng@v1
```

Use `--file` when you need to target a different local overlay path.

Execution begins only when `deploy` is given `--execute`:

```bash
hyops blueprint deploy --env <env> \
  --ref gcp/eve-ng@v1 \
  --blueprints-root blueprints \
  --execute
```

Use `--root /tmp/hyops-runtime` when an explicit runtime root is required. The
[GCP EVE-NG blueprint](gcp/eve-ng@v1/README.md) links to the complete operator
runbook.

## Existing lab migration

Existing EVE-NG and GNS3 labs can be inspected and staged before a new
HybridOps-managed host is deployed. Migration remains within the same lab
platform. The source host is not modified.

Save intended device configurations and stop the source nodes before capture:

```bash
hyops lab migrate capture \
  --platform eve-ng \
  --host <existing-host> \
  --user <ssh-user> \
  --output ./eve-ng-labs.tar.gz \
  --include-node-state \
  --include-images
```

OpenSSH uses its configured agent or keys and prompts for the account password
in an interactive terminal when required. HybridOps does not store that
password. Capture assesses all requested streams before transferring data.

Capture refuses to proceed while EVE-NG QEMU nodes or the GNS3 server are
running. Use `--become` when the SSH account has passwordless sudo access.
For EVE-NG, `--include-images` creates a separate archive containing only the
base images referenced by the captured labs. For GNS3, it includes the image
library in the primary archive. Capture uses `pigz -1` when available and
otherwise uses `gzip -1`. Sparse virtual disks remain sparse in the archive.

Inspect an archive first:

```bash
hyops lab migrate inspect \
  --platform eve-ng \
  --archive ./eve-ng-labs.tar.gz \
  --node-state ./eve-ng-labs.node-state.tar.gz \
  --images ./eve-ng-labs.images.tar.gz
```

Stage the verified bundle for an initialized environment:

```bash
hyops lab migrate import \
  --env <env> \
  --ref gcp/eve-ng@v1 \
  --platform eve-ng \
  --archive ./eve-ng-labs.tar.gz \
  --node-state ./eve-ng-labs.node-state.tar.gz \
  --images ./eve-ng-labs.images.tar.gz

hyops blueprint deploy \
  --env <env> \
  --ref gcp/eve-ng@v1 \
  --execute \
  --restore-labs
```

Existing lab definitions and base images are protected independently. Add
`--overwrite-labs` to replace lab definitions or `--overwrite-images` to
replace referenced base images. Neither flag is required on a new host.

The EVE-NG primary archive must be relative to `/opt/unetlab/labs`. Its
optional node-state companion contains stopped QEMU overlays using the EVE-NG
tenant, lab and node path layout. Its optional image companion contains only
referenced QEMU, IOL or Dynamips bases. Licence material is never included. A
GNS3 archive must be relative to its data root and contain `projects/` state.
Use the matching checksum options when checksums were recorded at the source.
Capture and import retain 64 MiB free on the controller filesystem. Restore
checks the target filesystem and stages image content before promotion.

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
