# EVE-NG network lab

`gcp/eve-ng@v1` delivers a private EVE-NG execution environment with governed access, health verification, device automation access, continuity preservation, rebuild and compute release.

The blueprint uses shared EVE-NG capability modules that are also used by the Proxmox path. Provider-specific infrastructure supplies the execution host; EVE-NG remains authoritative for topology and node behavior.

See [ARCHITECTURE.md](ARCHITECTURE.md) for the lifecycle and ownership model.

## What it delivers

- private nested-virtualization-capable execution compute with no public VM address
- EVE-NG installation and configuration through `platform/linux/eve-ng`
- declared starter images through `platform/linux/eve-ng-images`
- guest internet access through the EVE-NG `Cloud9` network
- private topology-node management through `Cloud8`
- service, database, API and KVM health verification
- archive-before-release through `platform/linux/eve-ng-lab-archive`
- verified restoration of lab definitions and selected stopped-QEMU overlay state
- structured run records and resource-age/cost context

## Execution chain

```text
private network
  -> execution host
  -> EVE-NG configuration
  -> lab images
  -> EVE-NG health verification
```

The executable contract is [blueprint.yml](blueprint.yml).

## Prepare and deploy

```bash
hyops setup gcp
hyops init gcp --env <env>
hyops secrets ensure --env <env> EVENG_ROOT_PASSWORD EVENG_ADMIN_PASSWORD

ref=gcp/eve-ng@v1
hyops blueprint init --env <env> --ref "$ref"
hyops blueprint validate --env <env> --ref "$ref"
hyops blueprint plan --env <env> --ref "$ref"
hyops blueprint preflight --env <env> --ref "$ref"
hyops blueprint deploy --env <env> --ref "$ref" --execute
```

The shipped host profile uses an `n2-standard-8` VM with 32 GB RAM, a 256 GB disk, Ubuntu 22.04 and nested virtualization. It is a reference profile that can be adjusted through the environment blueprint.

## Private access

Open the EVE-NG interface through the managed private path:

```bash
hyops blueprint access --env <env> --ref gcp/eve-ng@v1
```

The access session resolves the current host from HybridOps state and forwards the EVE-NG interface through IAP. The VM and EVE-NG HTTP service remain private.

For direct automation of topology nodes, connect a management interface to `Cloud8` and run:

```bash
hyops blueprint access --env <env> --ref gcp/eve-ng@v1 --automation
```

HybridOps discovers management leases and produces session-scoped SSH configuration and automation inventory. Linux and WSL can optionally use `--route-lab`; Windows and macOS clients can use the generated SSH configuration or local proxy path.

## Continuity and compute release

The blueprint declares `platform/linux/eve-ng-lab-archive` as its archive-before-release contract.

The retained set can contain:

- learner-created lab definitions under `/opt/unetlab/labs`; and
- stopped QEMU overlay state when node-state preservation is selected by the blueprint.

Before overlay capture, running QEMU nodes are stopped. Each retained archive is checksummed on the controller. Base images remain separately managed, so restored QEMU overlays reconnect to matching installed base images rather than copying those bases into the checkpoint.

For an explicit protected destroy:

```bash
hyops blueprint destroy --env <env> --ref gcp/eve-ng@v1 --execute --yes \
  --archive-before-destroy
```

A later deployment can restore the latest verified set:

```bash
hyops blueprint deploy --env <env> --ref gcp/eve-ng@v1 --execute --restore-labs
```

Restore verifies the lab archive and any node-state companion checksum before applying retained state. Existing content remains protected unless replacement is explicitly authorised.

## Rebuild

```bash
hyops blueprint rebuild --env <env> --ref gcp/eve-ng@v1 --execute
```

Rebuild applies the same lifecycle boundary: preserve the selected continuity state, release the current execution resources, recreate the host, restore verified state and return the lab through the normal EVE-NG readiness path.

## Shared implementation

The lab-platform layer is composed from:

- [EVE-NG configuration](../../../modules/platform/linux/eve-ng)
- [EVE-NG images](../../../modules/platform/linux/eve-ng-images)
- [EVE-NG health check](../../../modules/platform/linux/eve-ng-healthcheck)
- [EVE-NG lab archive](../../../modules/platform/linux/eve-ng-lab-archive)

The sibling [Proxmox implementation](../../onprem/eve-ng@v1) uses the same EVE-NG, health, access and archive contracts around a different execution-host lifecycle.
