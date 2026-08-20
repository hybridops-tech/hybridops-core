# GCP Containerlab v1

This blueprint runs Containerlab on private GCP compute that HybridOps can release after the selected recovery state has been copied off-host and verified.

## Responsibilities

Containerlab remains responsible for:

- `.clab.yml` topology semantics
- nodes and links
- topology validation and convergence
- native configuration save
- supported vrnetlab snapshot and restore
- generated lab runtime state
- supported startup-config and licence handling

HybridOps manages the GCP host around it: private infrastructure, KVM readiness, Containerlab version verification, recovery policy, off-host retention, compute-release and rebuild order, cost context, and run evidence.

HybridOps does not rewrite the topology or replace Containerlab recovery behaviour.

## Feature status

The GCP lifecycle is implemented on Core `main` and has completed end-to-end real-environment validation. The accepted path proved private GCP execution, IAP/SSH access, nested virtualisation and KVM readiness, Containerlab `0.78.0` deployment, independent lab health, off-host recovery verification before original VM deletion, reconstruction on a fresh VM with a different resource identity, one native Containerlab recovery deployment, final health, and final compute cleanup.

See [VALIDATION.md](VALIDATION.md) for the public validation boundary.

## Prepare the runtime blueprint

Create and edit the environment copy:

```bash
ref=gcp/containerlab@v1
hyops blueprint init --env <env> --ref "$ref"
hyops blueprint edit --env <env> --ref "$ref"
```

Set:

```text
gcp_containerlab_lab.inputs.containerlab_lab_source_dir
```

to an absolute controller-side directory containing `lab.clab.yml` and any relative local files it uses.

HybridOps copies the source tree without converting it to another topology format.

Containerlab-generated `clab-*` data stays outside that source tree using native `CLAB_LABDIR_BASE`:

```text
/var/lib/hybridops/containerlab/labdirs
```

If the topology uses proprietary or VM-backed NOS images, provide them from an image source the operator is authorised to use and that the managed host can reach. HybridOps does not distribute those images.

Remote startup-config or licence assets already supported by Containerlab should remain at their existing authoritative location and be referenced natively.

## Reference host

The validated reference profile uses:

- `n2-highmem-8`
- 8 vCPU
- 64 GB RAM
- Ubuntu 22.04
- 128 GB boot disk
- private IP
- nested virtualisation
- IAP/SSH access

This is a reference profile, not a sizing recommendation for every lab.

Containerlab `0.78.0` is pinned. HybridOps verifies the package against an explicit digest, a known pinned digest when available, or the release checksum file, then records the actual downloaded SHA-256.

## Deploy and rebuild flow

The deploy order is:

1. private GCP network
2. private GCP VM
3. Containerlab runtime and KVM check
4. native Containerlab deploy
5. independent health check
6. recovery check

The recovery check is last in deploy order, so reverse-order destroy reaches it before the lab, runtime, or VM is removed.

During destroy or rebuild HybridOps:

1. asks Containerlab for the native save output required by the selected policy
2. creates an immutable recovery archive
3. copies the archive to the HybridOps controller
4. verifies the SHA-256 off-host
5. writes the latest pointer, checksum, and metadata
6. allows Containerlab cleanup and GCP compute release only after verification passes

On a fresh host, HybridOps verifies the latest recovery metadata, imports the archive, restores the managed source path, and then runs one native Containerlab deploy. Supported vrnetlab snapshots are handed back through `containerlab deploy --restore-all`.

There is no fresh deploy followed by destroy and a second restore deploy.

## Recovery modes

### `rebuild`

Default. Keeps the source tree and supported native `save --copy` output.

Saved configuration is automatically reused only where the topology is already written to consume that native output. HybridOps does not rewrite startup-config references.

### `snapshot`

Also requests supported vrnetlab snapshots. Runtime-state recovery applies only to node kinds that Containerlab supports for this operation.

### `ephemeral`

Keeps source intent only. It does not preserve runtime state.

These modes are not a universal Containerlab backup mechanism.

## Off-host storage

Recovery archives are stored under the HybridOps runtime on the controller, outside the disposable GCP VM. This proves separation from the host being deleted, but it is not a separate backup service. Protect the controller storage according to the environment's own backup policy.

The timestamped archive is the retained object. `latest.tar.gz` is a symlink with matching checksum and metadata, so the archive bytes are not duplicated just to maintain a stable pointer.

Recovery archives may contain configuration or licence material and should remain private.

## Cost visibility

The blueprint shows the estimated fixed VM and boot-disk cost, resource age, access-session cost context, and the effect of compute release on declared resources.

The estimate does not include every usage charge, discount, credit, tax, or external service. GCP billing is authoritative for actual spend.

Removing the VM does not imply zero idle cost. Retained recovery storage, registries, or other resources may still be billable.

## Private host access

`hyops blueprint access` opens an IAP-backed local SSH forward. The default local endpoint is:

```text
127.0.0.1:2222
```

## Validation boundary

The validated GCP acceptance path established that:

- private GCP compute and IAP/SSH access were usable
- nested virtualisation and KVM readiness passed
- Containerlab `0.78.0` deployed the supplied topology and independent health passed
- the selected recovery set was copied and checksum-verified off-host before the original VM was deleted
- replacement compute had a different resource identity
- retained recovery state verified and imported on the fresh host
- reconstruction used one native Containerlab deployment
- final lab health passed
- final declared GCP compute was removed

The result is specific to the tested GCP lifecycle. It does not establish universal backup semantics for every Containerlab node kind, zero idle cost, or ownership of topology/recovery semantics by HybridOps.
