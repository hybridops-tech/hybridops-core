# GNS3 lifecycle architecture

The GNS3 implementation separates the lab platform from the execution-host lifecycle. GNS3 owns projects, topology and node execution. HybridOps governs the surrounding capacity, readiness, private access, continuity preservation, reconstruction and run evidence.

The same GNS3 capability modules are used by the Google Cloud and Proxmox blueprints. The execution-host layer changes; the lab-platform contract remains stable.

## Lifecycle

```text
execution capacity
      |
      v
GNS3 server
      |
      v
declared images + starter project
      |
      v
deep health verification
      |
      +------------------------------+
      |                              |
      v                              v
private GNS3 access          topology-node automation
      |                              |
      +--------------+---------------+
                     |
                     v
                  lab use
                     |
                     v
        preserve project state
                     |
                     v
           verify retained archive
                     |
                     v
             release execution host
                     |
                     v
          recreate execution capacity
                     |
                     v
        restore verified project state
                     |
                     v
             health verification
```

## Capability layers

| Layer | Responsibility |
| --- | --- |
| Execution host | Provider or virtualisation-specific capacity and private connectivity |
| GNS3 platform | Authenticated server, projects, topology and node execution |
| Image layer | Declared image acquisition and template preparation |
| Health layer | API, KVM, local-compute and starter-project verification |
| Access layer | Private GNS3 client path plus session-scoped topology-node management access |
| Continuity layer | Project directories, controller metadata and writable node disks retained away from the execution host |
| Cost context | Resource age, fixed-resource estimate and retained-resource visibility for cloud execution |
| Runtime evidence | Module state, archive checksum, health results, resource state and lifecycle records |

## Operating control points

The implementation crosses several operational disciplines, but each one resolves through the same lifecycle record.

| Control point | Decision | Evidence |
| --- | --- | --- |
| Readiness | Is execution capacity and GNS3 usable? | Provider state, preflight, API/KVM/local-compute/starter-project health |
| Private access | Can the operator and automation clients reach the required control surfaces? | Resolved runtime target, access session and generated client material |
| Continuity | What project state must survive this session? | Controller/project archive, manifest and SHA-256 value |
| Compute release | Is the high-resource execution host still required? | Verified retained archive and terminal resource state |
| Reconstruction | Has the project returned to a usable state? | Verified restore, API return and normal GNS3 health path |
| Cost context | Which cost-bearing resources are active or deliberately retained? | Resource age, fixed-resource estimate, terminal compute state and retained-resource reporting |

## Private access and device automation

The GNS3 server remains private. HybridOps resolves the current host from runtime state and establishes the access path for the session.

For topology-node automation, `hyops-mgmt0` is the management network. HybridOps discovers current DHCP leases and generates scoped SSH configuration, target data and automation inventory for the operator workstation. The node's own management service remains the protocol endpoint.

Live management addresses are session state. Durable role, platform, grouping and credential references can remain under operator or source-of-truth authority while the current endpoint is rediscovered after reconstruction.

## Continuity model

The blueprint configures `platform/linux/gns3-lab-archive` before destructive lifecycle actions.

The archive retains GNS3 project directories and controller metadata. Project directories contain topology, project files and writable node disks. The GNS3 service is stopped while controller state is copied or restored, providing a consistent archive boundary, then started again before the archive operation completes.

```text
GNS3 projects + controller metadata
                |
                v
       controller-side archive
                |
                v
         SHA-256 verification
                |
                v
          compute release
```

Base images are independently managed by default and can be reconstructed from their declarations. The archive can include the image library when policy explicitly selects that behavior.

## Restore path

`--restore-labs` selects the latest verified archive state recorded for the environment. The runtime verifies the recorded checksum before invoking the GNS3 archive module in restore mode.

A verified migration bundle can provide the initial project state for an
existing GNS3 installation. Intake checks the archive root, project
definitions, image references and checksum, then binds the retained copy to
this blueprint. The source host remains unchanged.

The restore operation stops the GNS3 service, applies the retained project and controller state, restores ownership, starts the service and waits for the API to return. The normal blueprint health path then verifies the reconstructed lab environment.

## Compute lifetime and cost boundary

Access closure and compute release are separate lifecycle events. Ending the GNS3 client, UI or SSH session leaves the execution host unchanged; the host becomes eligible for release when the retained project state has been verified under the selected continuity policy.

For the GCP path, HybridOps surfaces resource age and fixed-resource cost context alongside the lifecycle. Provider billing remains authoritative for realised spend. After execution compute is released, retained project archives, image sources, shared networking or other deliberately retained resources remain visible as separate state rather than being folded into the compute result.

This makes the cost decision operational rather than timer-based: continuity determines when high-resource compute can end, while the terminal resource record shows what still exists afterward. The Proxmox path uses the same continuity and terminal-state contract without the GCP billing context.

## Cross-target consistency

The GCP and Proxmox blueprints both declare:

- `platform/linux/gns3-server`
- `platform/linux/gns3-images`
- `platform/linux/gns3-starter-lab`
- `platform/linux/gns3-healthcheck`
- `platform/linux/gns3-lab-archive`
- the same `hyops-mgmt0` management subnet contract
- archive-before-release for project and writable node state

The provider-specific difference is the host and access transport. The GNS3 lifecycle, health, management and continuity contracts remain shared.

## Implementation references

- [Blueprint contract](blueprint.yml)
- [GNS3 server module](../../../modules/platform/linux/gns3-server)
- [GNS3 archive module](../../../modules/platform/linux/gns3-lab-archive)
- [Proxmox GNS3 blueprint](../../onprem/gns3@v1)
