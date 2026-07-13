# GCP EVE-NG Host

Build a private EVE-NG host on Google Cloud using a nested-virtualization-capable Compute Engine VM.

This blueprint provisions the VM, connects to it over GCP IAP, configures EVE-NG, and runs a health check so the host proves it is reachable. It is the cloud-friendly EVE-NG path for users who want a reproducible training or network-simulation host but do not have a Proxmox environment.

Use this when you want the EVE-NG host lifecycle to be rebuildable from infrastructure code instead of manually creating and patching a long-lived server.

## What This Delivers

- a private GCP Compute Engine VM for EVE-NG
- an isolated VPC, subnet, IAP SSH rule, router, and subnet-scoped Cloud NAT
- nested virtualization enabled for KVM-backed network simulation workloads
- no public IP by default
- SSH access through GCP IAP
- VM provisioning through `platform/gcp/platform-vm`
- EVE-NG installation and configuration through `platform/linux/eve-ng`
- a basic EVE-NG health check through `platform/linux/eve-ng-healthcheck`
- structured run records for each module step

## Execution Chain

```text
platform/gcp/lab-network
  -> platform/gcp/platform-vm
  -> platform/linux/eve-ng
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
- The placeholder `CHANGE_ME_GCP_ZONE` in [blueprint.yml](blueprint.yml) has been copied or overridden with a real zone that supports the selected machine family.

Seed the EVE-NG secrets before deployment:

```bash
hyops secrets ensure --env dev EVENG_ROOT_PASSWORD EVENG_ADMIN_PASSWORD
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
  --env dev \
  --ref gcp/eve-ng@v1 \
  --blueprints-root blueprints
```

Deploy:

```bash
hyops blueprint deploy \
  --env dev \
  --ref gcp/eve-ng@v1 \
  --blueprints-root blueprints \
  --execute
```

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

## Why This Exists

Not every networking learner or platform operator has a Proxmox cluster available. A cloud-hosted EVE-NG path makes the host lifecycle easier to reproduce from a clean state while still keeping access private and controlled.

This blueprint turns the EVE-NG host into a normal platform outcome:

- the VM is provisioned from a declared contract
- nested virtualization is explicitly enabled
- access goes through IAP instead of exposing SSH publicly
- EVE-NG configuration is a module step, not a manual shell session
- the final health check produces evidence that the EVE-NG host is reachable

That makes the EVE-NG host disposable enough to rebuild and predictable enough to share as part of a training or network-emulation workflow.

## Related Modules

- [platform/gcp/lab-network](../../../modules/platform/gcp/lab-network)
- [platform/gcp/platform-vm](../../../modules/platform/gcp/platform-vm)
- [platform/linux/eve-ng](../../../modules/platform/linux/eve-ng)
- [platform/linux/eve-ng-healthcheck](../../../modules/platform/linux/eve-ng-healthcheck)

## On-Prem Alternative

If you run Proxmox, the sibling [onprem/eve-ng@v1](../../onprem/eve-ng@v1) blueprint builds EVE-NG from a Proxmox template-image and VM provisioning chain.
