# GCP Containerlab v1

This blueprint runs Containerlab on private GCP compute that HybridOps can release after the selected recovery state has been copied off-host and verified.

## Responsibilities

Containerlab remains responsible for:

- `.clab.yml` topology semantics
- nodes and links
- topology validation and convergence
- native configuration save
- vrnetlab snapshot and restore where supported by the node type
- generated lab runtime state
- startup-config and licence handling supported by Containerlab

HybridOps governs the GCP execution lifecycle around the lab: private infrastructure, KVM readiness, Containerlab version verification, recovery policy, off-host retention, compute-release and rebuild order, cost context, and run evidence.

This separation keeps topology and native recovery authority with Containerlab while HybridOps governs when the execution host can be released and reconstructed.

## Feature status

The GCP lifecycle is implemented on Core `main` and has completed end-to-end real-environment validation. The accepted path proved private GCP execution, IAP/SSH access, nested virtualisation and KVM readiness, Containerlab `0.78.0` deployment, independent lab health, off-host recovery verification before original VM deletion, reconstruction on a fresh VM with a different resource identity, one native Containerlab recovery deployment, final health, and final compute cleanup.

See [VALIDATION.md](VALIDATION.md) for the validation record.

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

HybridOps copies the source tree while preserving the native Containerlab topology format.

Containerlab-generated `clab-*` data stays outside that source tree using native `CLAB_LABDIR_BASE`:

```text
/var/lib/hybridops/containerlab/labdirs
```

For proprietary or VM-backed NOS images, the operator supplies an authorised image source reachable by the managed host. Remote startup-config and licence assets remain at their authoritative locations and are referenced through Containerlab's native mechanisms.

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

Use this as the validated baseline and size other labs according to their workload requirements.

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
6. allows Containerlab cleanup and GCP compute release after verification passes

On fresh compute, HybridOps verifies the latest recovery metadata, imports the archive, restores the managed source path, and performs one native Containerlab deployment. Vrnetlab snapshots are returned through `containerlab deploy --restore-all` when the selected node types support that recovery path.

## Recovery modes

### `rebuild`

Default. Keeps the source tree and native `save --copy` output produced by the topology.

Saved configuration is reused when the topology references that native output.

### `snapshot`

Adds Containerlab-supported vrnetlab snapshots to the retained recovery set and returns them through native restore semantics on reconstruction.

### `ephemeral`

Keeps source intent and starts runtime state fresh on the next execution host.

The selected mode expresses the continuity outcome HybridOps must protect before compute release.

## Off-host storage

Recovery archives are stored under the HybridOps runtime on the controller, outside the disposable GCP VM. This establishes the first durable boundary beyond the host being released. The environment's backup policy can then protect that controller-side recovery store according to its retention requirements.

The timestamped archive is the retained object. `latest.tar.gz` is a symlink with matching checksum and metadata, so one immutable archive can also have a stable current pointer.

Recovery archives may contain configuration or licence material and should remain private.

## Cost visibility

The blueprint shows the estimated fixed VM and boot-disk cost, resource age, access-session cost context, and the effect of compute release on declared resources.

The estimate provides lifecycle decision context. GCP billing remains authoritative for realised spend, while retained recovery storage, registries, and other continuing resources remain visible as separate cost-bearing components.

## Private host access

`hyops blueprint access` opens an IAP-backed local SSH forward. The default local endpoint is:

```text
127.0.0.1:2222
```

Use the private node-management path with:

```bash
hyops blueprint access --env <env> --ref gcp/containerlab@v1 --automation
hyops blueprint device list --env <env> --ref gcp/containerlab@v1
hyops blueprint device web --env <env> --ref gcp/containerlab@v1 <device> --scheme https --port 443
```

HybridOps reads running node addresses from Containerlab inspection output. The default management network is `172.20.20.0/24`; change the runtime blueprint when the topology declares another subnet.

## Validated lifecycle

The GCP acceptance path established that:

- private GCP compute and IAP/SSH access were usable
- nested virtualisation and KVM readiness passed
- Containerlab `0.78.0` deployed the supplied topology and independent health passed
- the selected recovery set was copied and checksum-verified off-host before the original VM was deleted
- replacement compute had a different resource identity
- retained recovery state verified and imported on the fresh host
- reconstruction used one native Containerlab deployment
- final lab health passed
- final declared GCP compute was removed

This establishes a complete GCP continuity lifecycle around Containerlab: continuity policy selects the required recovery fidelity, off-host verification gates compute release, and reconstruction returns state through Containerlab's native capabilities on fresh execution capacity.
