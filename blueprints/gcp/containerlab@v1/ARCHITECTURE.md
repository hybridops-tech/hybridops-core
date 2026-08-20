# Containerlab on disposable GCP compute

## Problem

Some Containerlab labs need a large VM for only part of the day. Keeping that VM running only to preserve lab state is expensive.

Containerlab already owns topology, deployment, and the recovery features it supports. Before HybridOps removes the execution host, it must verify that the recovery data selected by policy has been copied somewhere that will survive that host.

## Ownership

### Containerlab

Containerlab remains responsible for:

- `.clab.yml` topology semantics
- nodes and links
- startup configuration handling
- topology validation
- deploy and convergence
- native `save`
- supported vrnetlab snapshot and restore
- lab inspection and generated runtime state
- supported local or remote startup-config and licence references

### HybridOps

HybridOps is responsible for:

- private GCP infrastructure
- nested virtualisation and KVM readiness
- Containerlab version and package verification
- image reachability checks without distributing vendor images
- VM lifetime and cost context
- recovery policy
- off-host recovery retention and checksum verification
- compute-release and rebuild order
- handing recovery data back to Containerlab
- recording the run result

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

HybridOps targets Containerlab `0.78.0` and uses native `validate`, `deploy`, `inspect`, `save`, `destroy`, and supported snapshot commands. HybridOps does not reproduce Containerlab topology or convergence logic.

Containerlab normally creates `clab-*` data beside the topology. HybridOps sets native `CLAB_LABDIR_BASE` to:

```text
/var/lib/hybridops/containerlab/labdirs
```

This keeps generated Containerlab data separate from the operator source tree. It does not create a new HybridOps lab-state format.

Containerlab can also use supported remote startup-config and licence references. Those assets should stay at their existing authoritative location. HybridOps only preserves local source material that would otherwise disappear with the disposable VM.

## What HybridOps does not do

HybridOps does not act as:

- a second topology engine
- a node or link reconciler
- a vendor configuration renderer
- a Containerlab snapshot implementation
- a Clabernetes replacement
- a proprietary NOS image repository
- a remote startup-config service
- a general backup product

## Recovery flow

The validated reference path uses a private `n2-highmem-8` VM with nested virtualisation.

Lab deployment, health checks, and recovery operations use the same `CLAB_LABDIR_BASE` value. The recovery step also checks that the managed source directory and generated labdir are different paths.

The recovery step is last in deploy order. Blueprint destroy runs in reverse order, so recovery runs before lab, runtime, and VM removal.

During destroy, HybridOps:

1. asks Containerlab for native save output and, in `snapshot` mode, supported vrnetlab snapshots
2. creates a timestamped archive
3. copies that archive to the HybridOps controller
4. verifies its SHA-256 there
5. restricts the retained archive permissions
6. updates the latest pointer, checksum, and metadata
7. allows compute release to continue only after the off-host check succeeds

The timestamped archive is the retained object. `latest.tar.gz` is only a symlink to it, with checksum and metadata stored alongside the link.

The controller filesystem is the first retention target. That proves the recovery copy survives deletion of the GCP VM, but the controller still needs its own backup policy.

## Rebuild flow

On a fresh host, HybridOps:

1. verifies the latest pointer, checksum, and metadata
2. verifies the immutable archive
3. checks topology identity when source matching is enabled
4. clears any stale import workspace
5. imports the archive
6. restores the source tree to the managed path
7. passes supported snapshots back to Containerlab
8. runs one native Containerlab deploy
9. runs the independent health check

There is no preliminary deploy that is destroyed before the real restore deploy.

## Recovery modes

`rebuild` keeps the source tree and supported native configuration-save output. Automatic reuse of saved configuration depends on how the topology is written.

`snapshot` also keeps Containerlab-supported vrnetlab snapshots. Unsupported node kinds may still start fresh.

`ephemeral` keeps source intent only.

## Validated lifecycle boundary

The real GCP acceptance path proved that the selected recovery set could be verified off-host before the original execution VM was removed, that reconstruction occurred on a fresh VM with a different resource identity through one native Containerlab deployment, and that the reconstructed lab passed independent health verification before final compute cleanup.

The validation record is maintained in [VALIDATION.md](VALIDATION.md).

## Remaining review questions

The implementation is complete for the validated GCP scope. External review is therefore about the operating boundary rather than whether the feature exists:

1. For a real Containerlab lab, which native state should be required to survive before a disposable execution host is released?
2. Where should the lifecycle refuse compute release because the required state cannot be externalised or reconstructed with sufficient fidelity?

Corrections and counterexamples can be raised against the implemented path without treating the feature as pre-release design work.
