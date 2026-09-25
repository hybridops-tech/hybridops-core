# EVE-NG on GCP

`gcp/eve-ng@v1` deploys a private EVE-NG environment on nested-virtualisation-capable GCP compute. The VM has no public address; configuration and access use IAP.

EVE-NG remains authoritative for topology and node behaviour. HybridOps manages host readiness, declared images, health verification, private access, lab preservation, reconstruction and compute release.

## Execution chain

```text
private network
  -> execution host
  -> EVE-NG configuration
  -> lab images
  -> EVE-NG health verification
```

The executable contract is [blueprint.yml](blueprint.yml). Initialise an environment copy before changing image sources, host sizing or optional licence inputs:

```bash
hyops blueprint init --env <env> --ref gcp/eve-ng@v1 --edit
```

EVE-NG credentials and authorised IOL licence content belong in the encrypted environment vault, not in the blueprint.

## Cost

The reference shape is `n2-standard-8` with a 256 GB `pd-standard` disk, sized
to leave room for nested workloads and images rather than to be the smallest
viable host. `machine_type`, `boot_disk_size_gb` and `eveng_resource_profile`
are declared in the environment copy and are not autoscaled.

Core reports a fixed hourly estimate on the access and destroy paths. `plan`
does not price a deployment, and provider billing remains authoritative for
realised spend.

Size from a representative running topology rather than node count alone.
Discussion [#291](https://github.com/hybridops-tech/hybridops-core/discussions/291)
records measured review points for lighter and denser topologies. A persistent
disk cannot be shrunk in place, so realising a disk reduction requires archive,
destroy and redeploy through the edited environment copy.

Plan the shape and session pattern before the first deploy when evaluating on
trial credit. The reference shape running continuously consumes a significant
share of an allowance within days, which is easy to overlook when lifecycle
work spans several sittings. Release the environment between sessions rather
than leaving it running.

Preservation covers lab definitions, saved device configurations and selected
stopped-node state. Declared base images are restored from configured sources.
Files outside those boundaries and undeclared images are not archived.

Before protected teardown, save device configurations and shut down QEMU guests
cleanly, or configure a quiescence action with `hyops blueprint quiescence edit`.
Stopped IOL nodes can be captured from saved NVRAM.

Use the protected destroy and restore path:

    hyops blueprint destroy --env <env> --ref gcp/eve-ng@v1 \
      --execute --archive-before-destroy

    hyops blueprint deploy --env <env> --ref gcp/eve-ng@v1 \
      --execute --restore-labs

That releases both the VM and the disk. Stopping the instance avoids compute
charges but leaves the disk billed and the environment outside the HybridOps
lifecycle; it is not a substitute for a verified archive.

## Private device access

Connect a device management interface to EVE-NG `Cloud8`. The device remains
private behind the EVE-NG host; no public device address is required.

Start the automation session and keep it running:

```bash
hyops blueprint access --env <env> --ref gcp/eve-ng@v1 --automation
```

Use another terminal to inspect and access the discovered targets:

```bash
hyops blueprint device list --env <env> --ref gcp/eve-ng@v1
hyops blueprint device edit --env <env> --ref gcp/eve-ng@v1
hyops blueprint device ssh --env <env> --ref gcp/eve-ng@v1 <device-name>
hyops blueprint device shell --env <env> --ref gcp/eve-ng@v1
```

DHCP discovery identifies a device by MAC address and refreshes its current
management address. Names, SSH users, identity files, platform details and
other fields set by the operator remain unchanged. Passwords do not belong in
the target file. Start a new automation session after editing it so generated
client material uses the updated values.

## Documentation

- [Operator runbook](https://docs.hybridops.tech/ops/runbooks/platform/blueprints/hyops-blueprint-eve-ng/)
- [Existing lab migration](../../../README.md#existing-lab-migration)
- [Lifecycle and ownership](ARCHITECTURE.md)
- [Proxmox blueprint](../../onprem/eve-ng@v1/blueprint.yml)
