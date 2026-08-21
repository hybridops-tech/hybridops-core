# Research and External Review

HybridOps Core is the public implementation examined by the technical papers below. Each paper starts from a focused operational question:

- When one operation crosses several control systems, what establishes that the whole operation is ready, verified and safely complete?
- When should a newly built machine image become a reusable infrastructure dependency?
- What must survive before high-resource lab compute can be released, and what must return when the lab is reconstructed on fresh execution capacity?
- Which record is authorised to supply a governed fact when intended, execution and observed state disagree?
- What evidence should govern recovery, service return, failback and residual state?

The papers state the claim, show the implemented boundary and provide a focused public review thread. Reviewers can assess one question without reviewing the whole repository.

## Research scope

Automation can succeed within each individual system while the wider operation remains wrong. It may act on stale authority, publish an image before consumer-path acceptance, report recovery before the service is usable, or release an environment before the required continuity state has been protected.

HybridOps makes those cross-system decisions explicit. It separates requested outcome from environment policy and implementation, resolves dependency order, evaluates readiness, publishes declared outputs, verifies results and records lifecycle transitions. Native platforms remain authoritative for the resources and mechanisms they own. HybridOps governs whether the wider operation may advance from declaration through execution, verification, publication, recovery and closure.

The constituent mechanisms are established engineering practice. HybridOps adds the runtime decision boundary that binds them into one operating contract: whether the cross-system operation may advance, publish, recover, release or close under its declared policy, dependency state and required observations. The implementation technologies provide the mechanisms; the contribution under review is the cross-system runtime contract they implement.

Review should test whether this boundary addresses a recognisable operating problem, whether the implementation supports the stated behaviour, and which partial-execution, recovery, authority, concurrency, implementation-substitution or scale case most strongly challenges it.

## Using the implementation maps

Each map points to three types of reference where relevant:

- **Public docs:** architecture context, reference scenarios, runbooks and the generated blueprint catalogue.
- **Declared operations:** shipped blueprint directories that show lifecycle declaration and supporting files together.
- **Runtime and module source:** code that implements the relevant contract, validation, lifecycle or evidence behaviour.

The [Blueprint Index](https://docs.hybridops.tech/platform/blueprints/) is the main catalogue for shipped operations, runbooks and source contracts. The repository [Blueprints directory](blueprints/) exposes the lifecycle declarations directly.

## Published technical papers

### Contract Runtime v1.2

**Question under review:** When one infrastructure operation crosses resource, configuration, platform, recovery and closure boundaries, does a separate runtime contract provide useful control over readiness, dependency state, verification and evidence?

**Paper:** https://hybridops.tech/papers/hybridops-contract-runtime-technical-review-v1.2.pdf

**Earlier reviewed editions:** [v1.1](https://hybridops.tech/papers/hybridops-contract-runtime-technical-review-v1.1.pdf) · [v1.0 institutional review edition](https://hybridops.tech/papers/hybridops-contract-runtime-technical-review-v1.0.pdf)

**Implementation map:**

- [Blueprint Index](https://docs.hybridops.tech/platform/blueprints/): catalogue of shipped operations, runbooks and source contracts.
- [Blueprint contract model](blueprints/): operating modes, intent, policy, delivery contracts, verification model and shipped operations.
- [On-Prem Authoritative Foundation](blueprints/onprem/authoritative-foundation@v1/): representative authority-gated blueprint chain.
- [`hyops blueprint` runtime](hyops/blueprint/command.py): validation, planning, preflight, deploy, rebuild, destroy and operator guardrails.
- [`hyops` command router](hyops/cli.py): runtime command registration and command-level run-record capture.
- [Preflight protocol](https://docs.hybridops.tech/architecture/contracts/hyops-preflight-contract/): readiness and validation contract.
- [Evidence and redaction standard](https://docs.hybridops.tech/architecture/standards/evidence-and-redaction/): run-record, traceability and redaction requirements.

**External review:** https://github.com/hybridops-tech/hybridops-core/issues/269

---

### Build, Boot, Verify, Publish v1.1

**Question under review:** What evidence should a newly built machine image satisfy before it is published as a reusable dependency, and how should that dependency later be re-verified or retired?

**Paper:** https://hybridops.tech/papers/build-boot-verify-publish-v1.1.pdf

**Earlier reviewed edition:** https://hybridops.tech/papers/build-boot-verify-publish-v1.0.pdf

**Implementation map:**

- [Capability Map](https://docs.hybridops.tech/evidence_map/): navigation for the image and bootstrap lifecycle and related runbooks.
- [Proxmox template-image module](modules/core/onprem/template-image/): Packer-driven construction, publication, clone-and-boot exercise, run-record outputs and implementation files.
- [On-Prem RKE2 operation](blueprints/onprem/rke2@v1/): builds a template, provisions VMs and installs RKE2.
- [Bootstrap NetBox operation](blueprints/onprem/bootstrap-netbox@v1/): consumes the image lifecycle in the wider SDN, VM, PostgreSQL and NetBox chain.
- [Blueprint Index](https://docs.hybridops.tech/platform/blueprints/): additional shipped operations that consume image-build steps.
- [Evidence and redaction standard](https://docs.hybridops.tech/architecture/standards/evidence-and-redaction/): persisted build, validation and execution records.

**External review:** https://github.com/hybridops-tech/hybridops-core/issues/270

---

### Separating Lab Continuity from Compute Lifetime v1.1

**Question under review:** For a high-resource network lab, what must survive before the execution host can be released between sessions, and what must return when the lab is reconstructed on fresh compute?

**Paper:** https://hybridops.tech/papers/separating-lab-continuity-from-compute-lifetime-v1.1.pdf

**Earlier reviewed edition:** https://hybridops.tech/papers/reproducible-network-training-labs-v1.0.pdf

**Implementation map:**

- [EVE-NG implementation](blueprints/gcp/eve-ng@v1/): private execution capacity, host and KVM readiness, EVE-NG health, private UI/console access, topology-node automation access, lab-definition preservation, selected stopped-QEMU overlay preservation, verified restoration and continuity-gated compute release.
- [EVE-NG lifecycle architecture](blueprints/gcp/eve-ng@v1/ARCHITECTURE.md): authority, access, preservation, reconstruction, evidence and compute-lifetime control points.
- [GNS3 implementation](blueprints/gcp/gns3@v1/): private execution capacity, authenticated server readiness, private UI/desktop access, topology-node automation access, project/controller/writable-disk preservation, verified reconstruction and lifecycle closure.
- [GNS3 lifecycle architecture](blueprints/gcp/gns3@v1/ARCHITECTURE.md): access, continuity, reconstruction, evidence and compute-lifetime control points.
- [Containerlab implementation](blueprints/gcp/containerlab@v1/): private host and KVM readiness, Containerlab installation, native topology deployment, independent health, off-host recovery verification, original-host release, fresh-host reconstruction through native Containerlab, final health and compute release.
- [Containerlab lifecycle architecture](blueprints/gcp/containerlab@v1/ARCHITECTURE.md): native authority and the surrounding execution/recovery lifecycle.
- [Blueprint Index](https://docs.hybridops.tech/platform/blueprints/): comparative catalogue of the shipped lab operations.

The three paths exercise different native state models while keeping the same outer lifecycle decision: execution compute becomes releasable after the selected continuity state has been preserved and verified, and reconstruction returns state through the lab platform that owns it.

**External review:** https://github.com/hybridops-tech/hybridops-core/issues/271

---

### Authority Before Automation v1.1

**Question under review:** When several records describe the same infrastructure fact, can an explicit authority declaration, bootstrap transfer and readiness gate prevent execution from acting on the wrong record?

**Paper:** https://hybridops.tech/papers/authority-before-automation-v1.1.pdf

**Earlier reviewed edition:** https://hybridops.tech/papers/authority-before-automation-v1.0.pdf

**Implementation map:**

- [Authoritative on-prem foundation reference scenario](https://docs.hybridops.tech/reference-scenarios/authoritative-onprem-foundation/): source-of-truth operating model and implementation narrative.
- [Bootstrap NetBox operation](blueprints/onprem/bootstrap-netbox@v1/): establishes the SDN, template, VMs, PostgreSQL and NetBox bootstrap chain.
- [Authoritative Foundation operation](blueprints/onprem/authoritative-foundation@v1/): uses NetBox-backed state to gate later platform VM expansion.
- [NetBox HA cutover operation](blueprints/onprem/netbox-ha-cutover@v1/): shows downstream state-contract consumption during service cutover.
- [Proxmox SDN operations runbook](https://docs.hybridops.tech/ops/runbooks/networking/sdn_operations/): plan, preflight and apply path for the network foundation that feeds authoritative inventory and IPAM.
- [Blueprint Index](https://docs.hybridops.tech/platform/blueprints/): bootstrap and authoritative operations in one catalogue.

**External review:** https://github.com/hybridops-tech/hybridops-core/issues/272

---

### Recovery Operating Model v1.1

**Question under review:** Do decision, readiness, workload-verification, service-transition, return and residual-state controls provide the evidence needed to govern recovery as one operating lifecycle?

**Paper:** https://hybridops.tech/papers/recovery-operating-model-v1.1.pdf

**Earlier reviewed edition:** https://hybridops.tech/papers/recovery-operating-model-v1.0.pdf

**Implementation map:**

- [PostgreSQL HA DR Cycle reference scenario](https://docs.hybridops.tech/reference-scenarios/postgresql-ha-dr-cycle/): restore to GCP, backup continuity, controlled failback and final DNS state.
- [PostgreSQL HA backup operation](blueprints/dr/postgresql-ha-backup-gcp@v1/): creates the GCS object repository and configures pgBackRest backup readiness.
- [PostgreSQL HA failover operation](blueprints/dr/postgresql-ha-failover-gcp@v1/): restores PostgreSQL HA in GCP and performs the DNS cutover path.
- [PostgreSQL HA failback operation](blueprints/dr/postgresql-ha-failback-onprem@v1/): rebuilds the on-premises path, restores the database, re-establishes backup and returns DNS.
- [GCP Ops Runner runbook](https://docs.hybridops.tech/ops/runbooks/networking/blueprints/hyops-blueprint-gcp-ops-runner/): runner-local execution model used for DR and burst workflows.
- [Blueprint Index](https://docs.hybridops.tech/platform/blueprints/): self-managed and managed PostgreSQL recovery operations in one catalogue.
- [Evidence and redaction standard](https://docs.hybridops.tech/architecture/standards/evidence-and-redaction/): stable non-secret execution records used to review recovery outcomes.

**External review:** https://github.com/hybridops-tech/hybridops-core/issues/273

## External review

Independent practitioners are invited to assess a paper against its corresponding public implementation. A full repository or code review is not expected.

Useful review areas include:

- whether the stated problem is recognisable in practice
- whether the proposed boundary adds useful control alongside the native system authorities
- whether the implementation and evidence support the stated claim
- which failure, authority, concurrency, recovery or scale case would challenge it

Specific criticism, corrections and counterexamples are welcome.
