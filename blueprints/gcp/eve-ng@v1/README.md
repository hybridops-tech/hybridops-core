# GCP EVE-NG Host

Build a private EVE-NG host on Google Cloud using a nested-virtualization-capable Compute Engine VM.

This blueprint provisions the VM, connects to it over GCP IAP, configures EVE-NG, loads a small starter image set, and runs a health check so the host proves it is reachable. It is the cloud-friendly EVE-NG path for users who want a reproducible training or network-simulation host but do not have a Proxmox environment.

Use this when you want the EVE-NG host lifecycle to be rebuildable from infrastructure code instead of manually creating and patching a long-lived server.

## What This Delivers

- a private GCP Compute Engine VM for EVE-NG
- an isolated VPC, subnet, IAP SSH rule, router, and subnet-scoped Cloud NAT
- nested virtualization enabled for KVM-backed network simulation workloads
- no public IP by default
- SSH access through GCP IAP
- VM provisioning through `platform/gcp/platform-vm`
- EVE-NG installation and configuration through `platform/linux/eve-ng`
- a starter image set through `platform/linux/eve-ng-images`
- a guest NAT network with DHCP for lab nodes that need outbound internet access
- a basic EVE-NG health check through `platform/linux/eve-ng-healthcheck`
- structured run records for each module step

## Execution Chain

```text
platform/gcp/lab-network
  -> platform/gcp/platform-vm
  -> platform/linux/eve-ng
  -> platform/linux/eve-ng-images
  -> platform/linux/eve-ng-healthcheck
```

The blueprint file is [blueprint.yml](blueprint.yml).

## Documentation

- [Deploy EVE-NG blueprint runbook](https://docs.hybridops.tech/ops/runbooks/platform/blueprints/hyops-blueprint-eve-ng/)
- [Reusable EVE-NG training environment reference scenario](https://docs.hybridops.tech/reference-scenarios/eveng-lab-foundation/)

## Prerequisites

This blueprint creates its own lab network. It assumes the GCP account and
target environment are ready:

- `hyops init gcp --env <env>` has been run.
- A GCP project is selected for the environment.
- Billing is enabled on the selected project. `hyops init gcp` and GCP module
  preflight stop when billing is disabled or cannot be confirmed. The deployment
  and running VM can consume free-trial credit or incur charges.
- The operator can create Compute Engine networks, firewall rules, routers,
  NAT configuration, and instances.
- EVE-NG secrets are seeded for the target environment.
- The VM zone is derived from the initialized GCP region. An environment
  overlay may select another zone in the same region when quota or capacity
  requires it; a zone from a different region is rejected before apply.

Seed the EVE-NG secrets before deployment:

```bash
hyops secrets ensure --env <env> EVENG_ROOT_PASSWORD EVENG_ADMIN_PASSWORD
```

## Usage

Validate the blueprint:

```bash
hyops blueprint validate \
  --ref gcp/eve-ng@v1 \
  --blueprints-root blueprints
```

Run preflight:

```bash
hyops blueprint preflight \
  --env <env> \
  --ref gcp/eve-ng@v1 \
  --blueprints-root blueprints
```

Open the private EVE-NG UI after deployment:

```bash
hyops blueprint access --env <env> --ref gcp/eve-ng@v1
```

HybridOps resolves the VM, project, and zone from module state, forwards HTTP
through the existing IAP SSH path with the declared HybridOps key, opens the
browser, and keeps access active until `Ctrl-C`. Port 80 remains closed at the
GCP firewall. Use `--no-browser` when only the printed local URL is required.

After an interactive access session closes, the blueprint reports billing
status and resource-state age, provides the project-specific GCP Billing link
for trial, credit and spend details, then offers to keep the environment,
export its lab definitions before teardown, or destroy without an export.
Destruction requires the operator to type `destroy <environment>`.

Automation must state the intended archive behaviour:

```bash
hyops blueprint destroy --env <env> --ref gcp/eve-ng@v1 --execute --yes \
  --archive-before-destroy
```

Use `--skip-archive` only when the current lab definitions are disposable.

Deploy:

```bash
hyops blueprint deploy \
  --env <env> \
  --ref gcp/eve-ng@v1 \
  --blueprints-root blueprints \
  --execute
```

When a verified lab archive exists for the environment, an interactive deploy
offers to restore it after the host is ready. For non-interactive recovery:

```bash
hyops blueprint deploy \
  --env <env> \
  --ref gcp/eve-ng@v1 \
  --execute \
  --restore-labs
```

The restore verifies the recorded checksum and protects existing lab
definitions. Add `--overwrite-labs` only when replacing existing definitions
is intentional.

Rebuild the blueprint-managed resources:

```bash
hyops blueprint rebuild \
  --env <env> \
  --ref gcp/eve-ng@v1 \
  --execute
```

The command shows the destroy and deploy order and requests confirmation before
the first destroy step.

## Default Shape

The shipped blueprint provisions one VM:

- logical name: `eve-ng-01`
- role: `eve-ng`
- machine type: `n2-standard-8`
- boot disk: `256` GB `pd-standard`
- source image: Ubuntu 22.04 LTS
- public IP: disabled
- nested virtualization: enabled
- SSH user: `opsadmin`
- network tag: `allow-iap-ssh`

The VM is placed on the private subnet created by the blueprint's lab-network
step.

The starter image set contains Alpine Linux, NETem, Tiny Core Linux, and Ubuntu
Server. Additional public image entries are retained as commented choices in
the blueprint. They are not downloaded unless an operator enables them. This
keeps the first deployment relatively small and avoids filling the VM disk with
desktop, security, and legacy images that a lab does not need.

The blueprint downloads enabled images from their upstream links at deployment
time. HybridOps does not include the image archives in its release package.

## Guest Internet Access

The EVE-NG host provides a guest NAT network labelled `Cloud9`. Connect a lab
node interface to `Cloud9` and configure that interface for DHCP. The node
receives an address from `172.29.129.50-172.29.129.200`, uses
`172.29.129.1` as its gateway, and reaches the internet through the EVE-NG
host's private GCP connection.

DHCP is supplied by the EVE-NG host, not by GCP. GCP provides the upstream
network path. No additional public IP is assigned to the lab node.

## Why This Exists

Not every networking learner or platform operator has a Proxmox cluster available. A cloud-hosted EVE-NG path makes the host lifecycle easier to reproduce from a clean state while still keeping access private and controlled.

This blueprint turns the EVE-NG host into a normal platform outcome:

- the VM is provisioned from a declared contract
- nested virtualization is explicitly enabled
- access goes through IAP instead of exposing SSH publicly
- EVE-NG configuration is a module step, not a manual shell session
- the declared starter images are installed before validation
- the final health check records whether the EVE-NG host is reachable

That makes the EVE-NG host disposable enough to rebuild and predictable enough to share as part of a training or network-emulation workflow.

## Related Modules

- [platform/gcp/lab-network](../../../modules/platform/gcp/lab-network)
- [platform/gcp/platform-vm](../../../modules/platform/gcp/platform-vm)
- [platform/linux/eve-ng](../../../modules/platform/linux/eve-ng)
- [platform/linux/eve-ng-images](../../../modules/platform/linux/eve-ng-images)
- [platform/linux/eve-ng-healthcheck](../../../modules/platform/linux/eve-ng-healthcheck)

## On-Prem Alternative

If you run Proxmox, the sibling [onprem/eve-ng@v1](../../onprem/eve-ng@v1) blueprint builds EVE-NG from a Proxmox template-image and VM provisioning chain.
