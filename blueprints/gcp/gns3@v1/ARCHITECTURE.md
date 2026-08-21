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
| Runtime evidence | Module state, archive checksum, health results, resource state and lifecycle records |

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

The restore operation stops the GNS3 service, applies the retained project and controller state, restores ownership, starts the service and waits for the API to return. The normal blueprint health path then verifies the reconstructed lab environment.

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
