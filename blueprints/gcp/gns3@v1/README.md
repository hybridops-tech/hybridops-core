# GNS3 network lab

`gcp/gns3@v1` delivers a private GNS3 execution environment with governed access, deep health verification, device automation access, project continuity, rebuild and compute release.

The blueprint uses shared GNS3 capability modules that are also used by the Proxmox path. Provider-specific infrastructure supplies the execution host; GNS3 remains authoritative for projects, topology and node execution.

See [ARCHITECTURE.md](ARCHITECTURE.md) for the lifecycle and ownership model.

## What it delivers

- private nested-virtualization-capable execution compute with no public VM address
- authenticated GNS3 server through `platform/linux/gns3-server`
- declared image handling through `platform/linux/gns3-images`
- a starter project through `platform/linux/gns3-starter-lab`
- deep GNS3, KVM and local-compute health verification
- private topology-node management through `hyops-mgmt0`
- archive-before-release through `platform/linux/gns3-lab-archive`
- verified restoration of projects, controller metadata and writable node disks
- structured run records and resource-age/cost context

## Execution chain

```text
private network
  -> execution host
  -> GNS3 server
  -> lab images
  -> starter project
  -> GNS3 health verification
```

The executable contract is [blueprint.yml](blueprint.yml).

## Prepare and deploy

```bash
hyops setup gcp
hyops init gcp --env <env>
hyops secrets ensure --env <env> GNS3_SERVER_PASSWORD

ref=gcp/gns3@v1
hyops blueprint init --env <env> --ref "$ref"
hyops blueprint validate --env <env> --ref "$ref"
hyops blueprint plan --env <env> --ref "$ref"
hyops blueprint preflight --env <env> --ref "$ref"
hyops blueprint deploy --env <env> --ref "$ref" --execute
```

The shipped host profile uses an `n2-standard-8` VM with 32 GB RAM, a 128 GB disk, Ubuntu 22.04 and nested virtualization. It is a reference profile that can be adjusted through the environment blueprint.

## Private access

Open the GNS3 server through the managed private path:

```bash
hyops blueprint access --env <env> --ref gcp/gns3@v1
```

Set a planned session limit when the environment must not remain active:

```bash
hyops blueprint access \
  --env <env> \
  --ref gcp/gns3@v1 \
  --session-minutes 120 \
  --on-expiry protected-release
```

The foreground access process supervises the limit and shows the UTC deadline
and warning intervals. The expiry action does not continue after that process
exits. At expiry, Core verifies the declared project archive before teardown.
A failed archive retains the environment.

Use `hyops blueprint session status`, `hyops blueprint session extend` or
`hyops blueprint session cancel` with the same environment and blueprint
reference. Extension also requires `--minutes <minutes>`.

The access session resolves the current host from HybridOps state and forwards the authenticated GNS3 API/UI endpoint through IAP. The VM and GNS3 service remain private.

Add `--native-consoles` when using the desktop client's Telnet, VNC, SPICE or web console handlers. HybridOps reads node console assignments from the authenticated GNS3 API and maintains matching loopback forwards while access remains open.

For direct automation of topology nodes, map a GNS3 Cloud node to `hyops-mgmt0`, connect device management interfaces to it and run:

```bash
hyops blueprint access --env <env> --ref gcp/gns3@v1 --automation
```

HybridOps discovers management leases and produces session-scoped SSH configuration, target data and automation inventory. Linux and WSL can optionally use `--route-lab`; Windows and macOS clients can use the generated SSH configuration or local proxy path.

While that session remains open, expose one device web interface on loopback:

```bash
hyops blueprint device web --env <env> --ref gcp/gns3@v1 <device> --scheme http --port 80
```

The device may be identified by target name or management IP. For several interfaces, use `hyops blueprint device edit` to declare each target's web service. The generated file documents the available fields. Open named targets together, or every declared service:

```bash
hyops blueprint device web --env <env> --ref gcp/gns3@v1 <device-1> <device-2>
hyops blueprint device web --env <env> --ref gcp/gns3@v1 --all
```

One Ctrl-C closes every tunnel. Add `--open-all` to open every URL in the workstation browser. Appliance certificates may produce the expected local browser warning.

Closing an interactive access session offers the same keep, archive or destroy decision as an explicit blueprint teardown.

## Continuity and compute release

The blueprint declares `platform/linux/gns3-lab-archive` as its archive-before-release contract.

The retained set contains GNS3 project directories and controller metadata. Project directories carry topology files, project files and writable node disks. The archive role stops the GNS3 server while controller state is copied or restored, then returns the service to its operating state.

Base images are separately managed by default and can be reconstructed from their declarations. The retained project archive therefore carries the mutable project state needed for continuation without coupling that state to the lifetime of the execution host.

For an explicit protected destroy:

```bash
hyops blueprint destroy --env <env> --ref gcp/gns3@v1 --execute --yes \
  --archive-before-destroy
```

A later deployment can restore the latest verified set:

```bash
hyops blueprint deploy --env <env> --ref gcp/gns3@v1 --execute --restore-labs
```

Restore verifies the recorded SHA-256 before applying the retained controller and project state.

## Rebuild

```bash
hyops blueprint rebuild --env <env> --ref gcp/gns3@v1 --execute
```

Rebuild applies the same lifecycle boundary: preserve the project state, release the current execution resources, recreate the host, restore the verified archive and return the lab through the normal GNS3 health path.

## Shared implementation

The lab-platform layer is composed from:

- [GNS3 server](../../../modules/platform/linux/gns3-server)
- [GNS3 images](../../../modules/platform/linux/gns3-images)
- [GNS3 starter lab](../../../modules/platform/linux/gns3-starter-lab)
- [GNS3 health check](../../../modules/platform/linux/gns3-healthcheck)
- [GNS3 lab archive](../../../modules/platform/linux/gns3-lab-archive)

The sibling [Proxmox implementation](../../onprem/gns3@v1) uses the same GNS3, health, access and archive contracts around a different execution-host lifecycle.
