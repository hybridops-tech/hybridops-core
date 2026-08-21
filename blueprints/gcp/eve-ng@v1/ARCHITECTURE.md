# EVE-NG lifecycle architecture

The EVE-NG implementation separates the lab platform from the execution-host lifecycle. EVE-NG owns topology and node behavior. HybridOps governs the surrounding capacity, readiness, private access, continuity preservation, reconstruction and run evidence.

The same EVE-NG capability modules are used by the Google Cloud and Proxmox blueprints. The execution-host layer changes; the lab-platform contract remains stable.

## Lifecycle

```text
execution capacity
      |
      v
EVE-NG configuration
      |
      v
authorised images
      |
      v
health verification
      |
      +------------------------------+
      |                              |
      v                              v
private UI access             topology-node automation
      |                              |
      +--------------+---------------+
                     |
                     v
                  lab use
                     |
                     v
      preserve selected continuity state
                     |
                     v
          verify retained archives
                     |
                     v
             release execution host
                     |
                     v
          recreate execution capacity
                     |
                     v
        restore verified retained state
                     |
                     v
             health verification
```

## Capability layers

| Layer | Responsibility |
| --- | --- |
| Execution host | Provider or virtualisation-specific capacity and private connectivity |
| EVE-NG platform | EVE-NG installation, services, topology and node execution |
| Image layer | Declared authorised image acquisition and placement |
| Health layer | Service, database, API and KVM readiness |
| Access layer | Private EVE-NG UI path plus session-scoped topology-node management access |
| Continuity layer | Lab definitions and selected stopped-QEMU overlay state, retained away from the execution host |
| Runtime evidence | Module state, checksums, health results, resource state and lifecycle records |

## Private access and device automation

The EVE-NG host remains private. HybridOps resolves the current host from runtime state and establishes the access path for the session.

For topology-node automation, EVE-NG `Cloud8` is the management network. HybridOps discovers current DHCP leases and generates scoped SSH configuration and automation inventory for the operator workstation. The node's own SSH, NETCONF/RESTCONF, gNMI, HTTPS or other management service remains the protocol endpoint.

Live management addresses are session state. Durable role, platform, grouping and credential references can remain under operator or source-of-truth authority while the current endpoint is rediscovered after reconstruction.

## Continuity model

The blueprint configures `platform/linux/eve-ng-lab-archive` before destructive lifecycle actions.

The primary archive retains EVE-NG lab definitions from `/opt/unetlab/labs`. The node-state companion path captures stopped QEMU overlays when node-state preservation is selected. The lifecycle stops running QEMU nodes before capture, validates the overlays and records a separate SHA-256 for the companion archive.

```text
EVE-NG lab definitions --------------------+
                                            |
stopped QEMU overlays, when selected -------+--> controller-side retained set
                                            |        |
                                            |        v
                                            |   SHA-256 verification
                                            |        |
                                            +--------+
                                                     |
                                                     v
                                               compute release
```

Vendor or base images remain separately managed. Restored overlays are paired with the matching installed base images. This keeps the retained continuity set focused on lab-owned mutable state.

## Restore path

`--restore-labs` selects the latest verified archive state recorded for the environment. The runtime verifies the primary archive checksum and, when present, the node-state companion checksum before invoking the archive module in restore mode.

Existing lab content is protected by default. Replacement requires the explicit overwrite option.

The restore path therefore reconstructs the surrounding execution environment while returning EVE-NG definitions and selected QEMU state to EVE-NG rather than translating them into another lab format.

## Cross-target consistency

The GCP and Proxmox blueprints both declare:

- `platform/linux/eve-ng`
- `platform/linux/eve-ng-images`
- `platform/linux/eve-ng-healthcheck`
- `platform/linux/eve-ng-lab-archive`
- the same `Cloud8` management subnet contract
- the same `Cloud9` guest-NAT contract
- archive-before-release with stopped-node capture enabled

The provider-specific difference is the host and access transport. The EVE-NG lifecycle, health, management and continuity contracts remain shared.

## Implementation references

- [Blueprint contract](blueprint.yml)
- [EVE-NG module](../../../modules/platform/linux/eve-ng)
- [EVE-NG archive module](../../../modules/platform/linux/eve-ng-lab-archive)
- [Proxmox EVE-NG blueprint](../../onprem/eve-ng@v1)
