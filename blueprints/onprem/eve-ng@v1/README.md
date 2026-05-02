# On-Prem EVE-NG Platform Stack

Build a rebuildable EVE-NG lab host on Proxmox instead of hand-maintaining a long-lived VM.

This blueprint consumes the shared on-prem SDN and NetBox authority, builds a verified Ubuntu Jammy template image, provisions an EVE-NG VM from that template, configures EVE-NG, and runs a health check so the host proves it is reachable.

Use this when you want the lab platform itself to be reproducible, not just the topologies that run inside EVE-NG.

## What This Delivers

- a Proxmox-hosted EVE-NG VM
- an Ubuntu 22.04 template image built through `core/onprem/template-image`
- post-build template smoke validation before the VM consumes the image
- IPAM-first VM provisioning through `platform/onprem/platform-vm`
- EVE-NG installation and configuration through `platform/linux/eve-ng`
- a basic EVE-NG health check through `platform/linux/eve-ng-healthcheck`
- structured run records for each module step

## Execution Chain

```text
core/onprem/template-image
  -> platform/onprem/platform-vm
  -> platform/linux/eve-ng
  -> platform/linux/eve-ng-healthcheck
```

The blueprint file is [blueprint.yml](blueprint.yml).

## Documentation

- [Deploy EVE-NG blueprint runbook](https://docs.hybridops.tech/ops/runbooks/platform/blueprints/hyops-blueprint-eve-ng/)
- [Reusable EVE-NG Lab Foundation reference scenario](https://docs.hybridops.tech/reference-scenarios/eveng-lab-foundation/)

## Prerequisites

This is a day-1 on-prem blueprint. It assumes the platform foundation already exists:

- Proxmox access is configured for HybridOps.
- The shared Proxmox SDN authority is ready.
- NetBox is available as IPAM and inventory authority.
- The `vnetmgmt` bridge exists in the SDN authority state.
- EVE-NG secrets are seeded for the target environment.

Seed the EVE-NG secrets before deployment:

```bash
hyops secrets ensure --env dev EVENG_ROOT_PASSWORD EVENG_ADMIN_PASSWORD
```

## Usage

Validate the blueprint:

```bash
hyops blueprint validate \
  --ref onprem/eve-ng@v1 \
  --blueprints-root blueprints
```

Run preflight:

```bash
hyops blueprint preflight \
  --env dev \
  --ref onprem/eve-ng@v1 \
  --blueprints-root blueprints
```

Deploy:

```bash
hyops blueprint deploy \
  --env dev \
  --ref onprem/eve-ng@v1 \
  --blueprints-root blueprints \
  --execute
```

## Default Shape

The shipped blueprint provisions one VM:

- logical name: `eve-ng-01`
- role: `eve-ng`
- CPU: `8` cores
- memory: `32768` MB
- disk: `256` GB
- network: `vnetmgmt`
- SSH user: `opsadmin`

The VM consumes the template state from:

```text
core/onprem/template-image#template_image_ubuntu_22_04
```

Addressing is IPAM-driven. The VM module reads NetBox and the shared SDN authority instead of hardcoding an address into the blueprint.

## Why This Exists

EVE-NG is often treated as a manually built lab box: install it once, patch it carefully, and hope nobody needs to recreate it from scratch.

This blueprint turns that host into a normal platform outcome:

- the base image is built from a repeatable definition
- the template is smoke-checked before use
- the VM is provisioned from state, not from a remembered VMID
- EVE-NG configuration is a module step, not a manual shell session
- the final health check produces evidence that the lab host is reachable

That makes the lab host disposable enough to rebuild and predictable enough to use as part of a wider training or network-emulation platform.

## Related Modules

- [core/onprem/template-image](../../../modules/core/onprem/template-image)
- [platform/onprem/platform-vm](../../../modules/platform/onprem/platform-vm)
- [platform/linux/eve-ng](../../../modules/platform/linux/eve-ng)
- [platform/linux/eve-ng-healthcheck](../../../modules/platform/linux/eve-ng-healthcheck)

## Cloud Alternative

If you do not have Proxmox, the sibling [gcp/eve-ng@v1](../../gcp/eve-ng@v1) blueprint provisions a private nested-virtualization-capable GCP VM, configures EVE-NG over IAP, and runs the same health-check pattern.
