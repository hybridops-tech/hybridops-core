# Containerlab on disposable GCP compute

## Problem

Some Containerlab labs need a large VM for only part of the day. Keeping that VM running solely to preserve lab state extends the lifetime and cost of execution capacity beyond the active lab session.

HybridOps separates those concerns. Containerlab owns topology, deployment and native recovery semantics. HybridOps verifies that the recovery state selected by policy has survived beyond the execution host before that host is released.

## Ownership

### Containerlab

Containerlab remains responsible for:

- `.clab.yml` topology semantics
- nodes and links
- startup configuration handling
- topology validation
- deploy and convergence
- native `save`
- vrnetlab snapshot and restore where supported
- lab inspection and generated runtime state
- local or remote startup-config and licence references supported by Containerlab

### HybridOps

HybridOps is responsible for:

- private GCP infrastructure
- nested virtualisation and KVM readiness
- Containerlab version and package verification
- image reachability checks
- VM lifetime and cost context
- recovery policy
- off-host recovery retention and checksum verification
- compute-release and rebuild order
- handing recovery data back through Containerlab
- recording the lifecycle result

```text
.clab.yml and native recovery data
                |
                v
          Containerlab
 topology / nodes / links / convergence / native recovery
                |
---------------- ownership boundary ----------------
                |
            HybridOps
 readiness / off-host copy / GCP rebuild / verification
                |
                v
        disposable GCP compute
```

## Native Containerlab behaviour used by HybridOps

HybridOps targets Containerlab `0.78.0` and uses native `validate`, `deploy`, `inspect`, `save`, `destroy`, and snapshot commands supported by the selected node types. Containerlab remains the topology and convergence engine throughout the lifecycle.

Containerlab normally creates `clab-*` data beside the topology. HybridOps sets native `CLAB_LABDIR_BASE` to:

```text
/var/lib/hybridops/containerlab/labdirs
```

This keeps generated Containerlab data separate from the operator source tree while retaining Containerlab's native state layout.

Remote startup-config and licence assets remain at their authoritative locations and are referenced through Containerlab. Local source material required for reconstruction is included in the selected recovery set.

## Authority model

The architecture keeps each responsibility with the system that owns its semantics:

| Concern | Authority |
| --- | --- |
| Topology, nodes, links and convergence | Containerlab |
| Native save, snapshot and restore behaviour | Containerlab |
| Proprietary NOS image and licence rights | Operator / authorised source |
| GCP host lifecycle and private access | HybridOps |
| Recovery policy and release gate | HybridOps |
| Off-host archive integrity | HybridOps recovery record |
| Realised cloud spend | GCP billing |

This allows HybridOps to govern execution lifetime while Containerlab continues to govern the lab itself.

## Recovery flow

The validated reference path uses a private `n2-highmem-8` VM with nested virtualisation.

Lab deployment, health checks, and recovery operations use the same `CLAB_LABDIR_BASE` value. The recovery step also checks that the managed source directory and generated labdir are different paths.

The recovery step is last in deploy order. Blueprint destroy runs in reverse order, so recovery runs before lab, runtime, and VM removal.

During compute release, HybridOps:

1. asks Containerlab for native save output and, in `snapshot` mode, supported vrnetlab snapshots
2. creates a timestamped archive
3. copies that archive to the HybridOps controller
4. verifies its SHA-256 there
5. restricts the retained archive permissions
6. updates the latest pointer, checksum, and metadata
7. releases compute after the off-host check succeeds

The timestamped archive is the retained object. `latest.tar.gz` is a symlink to it, with checksum and metadata stored alongside the link.

The controller filesystem is the first retention target beyond the disposable VM. Environment backup policy can extend that protection according to the required retention period.

## Rebuild flow

On fresh compute, HybridOps:

1. verifies the latest pointer, checksum, and metadata
2. verifies the immutable archive
3. checks topology identity when source matching is enabled
4. clears any stale import workspace
5. imports the archive
6. restores the source tree to the managed path
7. passes supported snapshots back to Containerlab
8. performs one native Containerlab deployment
9. runs the independent health check

A verified existing-lab migration import publishes the same latest pointer,
checksum and metadata contract. The rebuild path therefore restores an
imported source tree without a separate deployment mode.

## Recovery modes

`rebuild` keeps the source tree and native configuration-save output produced by the topology. Automatic configuration reuse follows the topology's existing startup-config references.

`snapshot` adds Containerlab-supported vrnetlab snapshots to the retained recovery set and returns them through native restore semantics.

`ephemeral` keeps source intent and starts runtime state fresh on the next execution host.

## Validated lifecycle

The real GCP acceptance path proved that the selected recovery set could be verified off-host before the original execution VM was removed, reconstruction occurred on a fresh VM with a different resource identity through one native Containerlab deployment, the reconstructed lab passed independent health verification, and final execution compute was released.

The validation record is maintained in [VALIDATION.md](VALIDATION.md).

## Practitioner review questions

The implementation is complete for the validated GCP lifecycle. External review can now test the operating model against real Containerlab practice:

1. For a real Containerlab lab, which native state should be required to survive before a disposable execution host is released?
2. Which topology or workload conditions should keep the release gate closed until a higher-fidelity recovery mechanism is available?

Corrections, counterexamples and additional recovery requirements can be raised directly against the implemented path.
