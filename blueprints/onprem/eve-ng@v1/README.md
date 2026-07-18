# On-Prem EVE-NG Platform Stack

Build a rebuildable EVE-NG host on Proxmox instead of hand-maintaining a long-lived VM.

This blueprint builds a verified Ubuntu Jammy template image, provisions a standalone EVE-NG VM from that template, configures EVE-NG, installs a starter image set, and runs a health check.

Use this when you want the EVE-NG platform itself to be reproducible, not just the topologies that run inside it.

## What This Delivers

- a Proxmox-hosted EVE-NG VM
- an Ubuntu 22.04 template image built through `core/onprem/template-image`
- post-build template smoke validation before the VM consumes the image
- standalone VM provisioning through `platform/onprem/platform-vm`
- EVE-NG installation and configuration through `platform/linux/eve-ng`
- a small public starter-image set through `platform/linux/eve-ng-images`
- a managed `Cloud9` guest network with DHCP and outbound connectivity
- a basic EVE-NG health check through `platform/linux/eve-ng-healthcheck`
- structured run records for each module step

## Execution Chain

```text
core/onprem/template-image
  -> platform/onprem/platform-vm
  -> platform/linux/eve-ng
  -> platform/linux/eve-ng-images
  -> platform/linux/eve-ng-healthcheck
```

The blueprint file is [blueprint.yml](blueprint.yml).

## Documentation

- [Deploy EVE-NG blueprint runbook](https://docs.hybridops.tech/ops/runbooks/platform/blueprints/hyops-blueprint-eve-ng/)
- [Reusable EVE-NG training environment reference scenario](https://docs.hybridops.tech/reference-scenarios/eveng-lab-foundation/)

## Prerequisites

The standalone path requires:

- Proxmox access is configured for HybridOps.
- The Proxmox `vmbr0` bridge provides DHCP connectivity for the VM.
- EVE-NG secrets are seeded for the target environment.

NetBox and shared Proxmox SDN remain available for managed platform deployments, but they are not required for this lab blueprint.

Seed the EVE-NG secrets before deployment:

```bash
hyops secrets ensure --env <env> EVENG_ROOT_PASSWORD EVENG_ADMIN_PASSWORD
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
  --env <env> \
  --ref onprem/eve-ng@v1 \
  --blueprints-root blueprints
```

Deploy:

```bash
hyops blueprint deploy \
  --env <env> \
  --ref onprem/eve-ng@v1 \
  --blueprints-root blueprints \
  --execute
```

Open the private UI:

```bash
hyops blueprint access --env <env> --ref onprem/eve-ng@v1
```

When access closes, HybridOps offers to keep the environment, export its lab
definitions before teardown, or destroy without an export. Direct interactive
destroy uses the same choices. Automation must pass either
`--archive-before-destroy` or `--skip-archive` with `--yes`.

After redeployment, an interactive deploy offers to restore a verified archive.
For non-interactive recovery:

```bash
hyops blueprint deploy \
  --env <env> \
  --ref onprem/eve-ng@v1 \
  --execute \
  --restore-labs
```

The archive checksum is verified before restoration. Existing lab definitions
are protected unless `--overwrite-labs` is also supplied.

## Default Shape

The shipped blueprint provisions one VM:

- logical name: `eve-ng-01`
- role: `eve-ng`
- CPU: `8` cores
- memory: `32768` MB
- disk: `256` GB
- network: `vmbr0` with DHCP
- guest egress network: `Cloud9` (`172.29.129.0/24`)
- SSH user: `opsadmin`

The VM consumes the template state from:

```text
core/onprem/template-image#template_image_ubuntu_22_04
```

The VM obtains its management address through DHCP on the normal Proxmox uplink. No address is hardcoded into the blueprint.

## Why This Exists

EVE-NG is often treated as a manually built appliance: install it once, patch it carefully, and hope nobody needs to recreate it from scratch.

This blueprint turns that host into a normal platform outcome:

- the base image is built from a repeatable definition
- the template is smoke-checked before use
- the VM is provisioned from state, not from a remembered VMID
- EVE-NG configuration is a module step, not a manual shell session
- the declared starter images are installed as a separate repeatable step
- the final health check records whether the EVE-NG host is reachable

That makes the EVE-NG host disposable enough to rebuild and predictable enough to use as part of a wider training or network-emulation platform.

## Related Modules

- [core/onprem/template-image](../../../modules/core/onprem/template-image)
- [platform/onprem/platform-vm](../../../modules/platform/onprem/platform-vm)
- [platform/linux/eve-ng](../../../modules/platform/linux/eve-ng)
- [platform/linux/eve-ng-images](../../../modules/platform/linux/eve-ng-images)
- [platform/linux/eve-ng-healthcheck](../../../modules/platform/linux/eve-ng-healthcheck)

## Cloud Alternative

If you do not have Proxmox, the sibling [gcp/eve-ng@v1](../../gcp/eve-ng@v1) blueprint provisions a private nested-virtualization-capable GCP VM, configures EVE-NG over IAP, and runs the same health-check pattern.
