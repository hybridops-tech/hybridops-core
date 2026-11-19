# Research and External Review

HybridOps technical papers examine operating boundaries implemented in Core.
Each paper defines one question, maps it to the implementation and
documentation, and provides a focused review thread.

## Research scope

A local action can succeed while the wider operation remains incomplete. It may
use stale authority, publish an image before consumer-path acceptance, report
recovery before service return, or release compute before continuity state is
protected.

HybridOps treats the operation as an executable contract. The runtime separates
requested outcome, environment policy and versioned implementation, resolves
dependencies, evaluates readiness, dispatches ordered stages, verifies declared
acceptance conditions and records lifecycle transitions. Resource platforms
remain authoritative for their own live state.

## Papers

| Paper | Review question | Public review | Earlier editions |
|---|---|---|---|
| [Contract Runtime v1.2](https://hybridops.tech/papers/hybridops-contract-runtime-technical-review-v1.2.pdf) | How should readiness, dependencies, verification and closure be governed when one operation crosses several control systems? | [Issue #269](https://github.com/hybridops-tech/hybridops-core/issues/269) | [v1.1](https://hybridops.tech/papers/hybridops-contract-runtime-technical-review-v1.1.pdf) · [v1.0](https://hybridops.tech/papers/hybridops-contract-runtime-technical-review-v1.0.pdf) |
| [Build, Boot, Verify, Publish v1.1](https://hybridops.tech/papers/build-boot-verify-publish-v1.1.pdf) | What evidence should a machine image satisfy before publication as a reusable dependency? | [Issue #270](https://github.com/hybridops-tech/hybridops-core/issues/270) | [v1.0](https://hybridops.tech/papers/build-boot-verify-publish-v1.0.pdf) |
| [Separating Lab Continuity from Compute Lifetime v1.1](https://hybridops.tech/papers/separating-lab-continuity-from-compute-lifetime-v1.1.pdf) | What must survive before high-resource lab compute is released, and what must return on fresh execution capacity? | [Issue #271](https://github.com/hybridops-tech/hybridops-core/issues/271) | [v1.0](https://hybridops.tech/papers/reproducible-network-training-labs-v1.0.pdf) |
| [Authority Before Automation v1.1](https://hybridops.tech/papers/authority-before-automation-v1.1.pdf) | Which record may supply a governed fact when intended, execution and observed state disagree? | [Issue #272](https://github.com/hybridops-tech/hybridops-core/issues/272) | [v1.0](https://hybridops.tech/papers/authority-before-automation-v1.0.pdf) |
| [Recovery Operating Model v1.1](https://hybridops.tech/papers/recovery-operating-model-v1.1.pdf) | What evidence should govern recovery, service return, failback and residual state? | [Issue #273](https://github.com/hybridops-tech/hybridops-core/issues/273) | [v1.0](https://hybridops.tech/papers/recovery-operating-model-v1.0.pdf) |

## Implementation maps

The [Blueprint Index](https://docs.hybridops.tech/platform/blueprints/) catalogues
shipped operations and runbooks. The repository [blueprint directories](blueprints/)
expose their lifecycle declarations and supporting files.

### Contract Runtime

- [Blueprint contract model](blueprints/): operating modes, intent, policy,
  delivery contracts, verification and shipped operations.
- [On-Prem Authoritative Foundation](blueprints/onprem/authoritative-foundation@v1/):
  representative authority-gated blueprint chain.
- [`hyops blueprint` runtime](hyops/blueprint/command.py): validation, planning,
  preflight, deploy, rebuild, destroy and operator guardrails.
- [`hyops` command router](hyops/cli.py): runtime command registration and
  command-level run-record capture.
- [Preflight protocol](https://docs.hybridops.tech/architecture/contracts/hyops-preflight-contract/):
  readiness and validation contract.
- [Evidence and redaction standard](https://docs.hybridops.tech/architecture/standards/evidence-and-redaction/):
  run-record, traceability and redaction requirements.

### Build, Boot, Verify, Publish

- [Capability Map](https://docs.hybridops.tech/evidence_map/): image and bootstrap
  lifecycle navigation and related runbooks.
- [Proxmox template-image module](modules/core/onprem/template-image/):
  Packer-driven construction, publication, clone-and-boot exercise, run-record
  outputs and implementation files.
- [On-Prem RKE2 operation](blueprints/onprem/rke2@v1/): builds a template,
  provisions VMs and installs RKE2.
- [Bootstrap NetBox operation](blueprints/onprem/bootstrap-netbox@v1/): consumes
  the image lifecycle in the wider SDN, VM, PostgreSQL and NetBox chain.
- [Evidence and redaction standard](https://docs.hybridops.tech/architecture/standards/evidence-and-redaction/):
  persisted build, validation and execution records.

### Separating Lab Continuity from Compute Lifetime

- [EVE-NG implementation](blueprints/gcp/eve-ng@v1/): private execution capacity,
  host and KVM readiness, EVE-NG health, private UI and console access,
  topology-node automation access, lab-definition preservation, selected
  stopped-QEMU overlay preservation, verified restoration and continuity-gated
  compute release.
- [EVE-NG lifecycle architecture](blueprints/gcp/eve-ng@v1/ARCHITECTURE.md):
  authority, access, preservation, reconstruction, evidence and compute-lifetime
  control points.
- [GNS3 implementation](blueprints/gcp/gns3@v1/): private execution capacity,
  authenticated server readiness, private UI and desktop access, topology-node
  automation access, project, controller and writable-disk preservation,
  verified reconstruction and lifecycle closure.
- [GNS3 lifecycle architecture](blueprints/gcp/gns3@v1/ARCHITECTURE.md): access,
  continuity, reconstruction, evidence and compute-lifetime control points.
- [Containerlab implementation](blueprints/gcp/containerlab@v1/): private host
  and KVM readiness, Containerlab installation, native topology deployment,
  independent health, off-host recovery verification, original-host release,
  fresh-host reconstruction through native Containerlab, final health and
  compute release.
- [Containerlab lifecycle architecture](blueprints/gcp/containerlab@v1/ARCHITECTURE.md):
  native authority and the surrounding execution and recovery lifecycle.

These paths apply the same outer lifecycle decision to different native state
models: compute is releasable only after the selected continuity state is
preserved and verified, and reconstruction returns state through the platform
that owns it.

### Authority Before Automation

- [Authoritative on-prem foundation reference scenario](https://docs.hybridops.tech/reference-scenarios/authoritative-onprem-foundation/):
  source-of-truth operating model and implementation narrative.
- [Bootstrap NetBox operation](blueprints/onprem/bootstrap-netbox@v1/):
  establishes the SDN, template, VM, PostgreSQL and NetBox bootstrap chain.
- [Authoritative Foundation operation](blueprints/onprem/authoritative-foundation@v1/):
  uses NetBox-backed state to gate later platform VM expansion.
- [NetBox HA cutover operation](blueprints/onprem/netbox-ha-cutover@v1/):
  downstream state-contract consumption during service cutover.
- [Proxmox SDN operations runbook](https://docs.hybridops.tech/ops/runbooks/networking/sdn_operations/):
  plan, preflight and apply path for the network foundation that feeds
  authoritative inventory and IPAM.

### Recovery Operating Model

- [PostgreSQL HA DR Cycle reference scenario](https://docs.hybridops.tech/reference-scenarios/postgresql-ha-dr-cycle/):
  restoration to GCP, backup continuity, controlled failback and final DNS
  state.
- [PostgreSQL HA backup operation](blueprints/dr/postgresql-ha-backup-gcp@v1/):
  creates the GCS object repository and configures pgBackRest backup readiness.
- [PostgreSQL HA failover operation](blueprints/dr/postgresql-ha-failover-gcp@v1/):
  restores PostgreSQL HA in GCP and performs the DNS cutover path.
- [PostgreSQL HA failback operation](blueprints/dr/postgresql-ha-failback-onprem@v1/):
  rebuilds the on-premises path, restores the database, re-establishes backup
  and returns DNS.
- [GCP Ops Runner runbook](https://docs.hybridops.tech/ops/runbooks/networking/blueprints/hyops-blueprint-gcp-ops-runner/):
  runner-local execution model used for recovery and burst workflows.
- [Evidence and redaction standard](https://docs.hybridops.tech/architecture/standards/evidence-and-redaction/):
  stable non-secret records for reviewing recovery outcomes.

## External review

Review may address the operating problem, the proposed boundary, the supporting
implementation and evidence, or a failure, authority, concurrency, recovery or
scale case that challenges the claim. Corrections and counterexamples are
welcome.
