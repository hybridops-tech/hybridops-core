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
| Cost context | Resource age, fixed-resource estimate and retained-resource visibility for cloud execution |
| Runtime evidence | Module state, checksums, health results, resource state and lifecycle records |

## Operating control points

The implementation crosses several operational disciplines, but each one resolves through the same lifecycle record.

| Control point | Decision | Evidence |
| --- | --- | --- |
| Readiness | Is execution capacity and EVE-NG usable? | Provider state, preflight, service/database/API/KVM health |
| Private access | Can the operator and automation clients reach the required control surfaces? | Resolved runtime target, access session and generated client material |
| Continuity | What state must survive this session? | Lab archive, optional stopped-QEMU overlay archive, manifests and SHA-256 values |
| Compute release | Is the high-resource execution host still required? | Verified retained recovery set and terminal resource state |
| Reconstruction | Has the lab returned to a usable state? | Verified restore followed by the normal EVE-NG health path |
| Cost context | Which cost-bearing resources are active or deliberately retained? | Resource age, fixed-resource estimate, terminal compute state and retained-resource reporting |

## Private access and device automation

The EVE-NG host remains private. HybridOps resolves the current host from runtime state and establishes the access path for the session.

For topology-node automation, EVE-NG `Cloud8` is the management network. HybridOps discovers current DHCP leases and generates scoped SSH configuration and automation inventory for the operator workstation. The node's own SSH, NETCONF/RESTCONF, gNMI, HTTPS or other management service remains the protocol endpoint.

Live management addresses are session state. Durable role, platform, grouping and credential references can remain under operator or source-of-truth authority while the current endpoint is rediscovered after reconstruction.

## Continuity model

The blueprint configures `platform/linux/eve-ng-lab-archive` before destructive lifecycle actions.

The primary archive retains EVE-NG lab definitions from `/opt/unetlab/labs` after EVE-NG refreshes saved device configurations in those definitions. The node-state companion path captures stopped QEMU overlays when node-state preservation is selected. The lifecycle stops running QEMU nodes before overlay capture, validates the overlays and records a separate SHA-256 for the companion archive.

```text
lab definitions and saved configurations --+
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

Base images remain separately managed during routine preservation. A verified migration intake can carry only the bases referenced by the imported labs. Restored overlays are paired with those installed bases.

## Restore path

`--restore-labs` selects the latest verified archive state recorded for the environment. The runtime verifies the primary archive checksum and, when present, the node-state companion checksum before invoking the archive module in restore mode.

A verified migration bundle can provide the initial archive state for an
existing EVE-NG lab. Intake checks its lab definitions, archive paths, image
references and optional QEMU overlay layout, then binds the retained copy to
this blueprint. The source host remains unchanged.

Existing lab definitions and base images are protected independently. Replacement requires `--overwrite-labs` or `--overwrite-images` for the relevant content.

The restore path reconstructs the surrounding execution environment while returning EVE-NG definitions and selected QEMU state to EVE-NG rather than translating them into another lab format.

## Compute lifetime and cost boundary

Access closure and compute release are separate lifecycle events. Ending a browser, console or SSH session leaves the execution host unchanged; the host becomes eligible for release when the selected continuity state has been preserved and verified.

For the GCP path, HybridOps surfaces resource age and fixed-resource cost context alongside the lifecycle. Provider billing remains authoritative for realised spend. After execution compute is released, retained archives, image sources, shared networking or other deliberately retained resources remain visible as separate state rather than being folded into the compute result.

This makes the cost decision operational rather than timer-based: continuity determines when high-resource compute can end, while the terminal resource record shows what still exists afterward. The Proxmox path uses the same continuity and terminal-state contract without the GCP billing context.

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
