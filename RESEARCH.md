# Research and External Review

HybridOps Core is the public implementation examined by the technical papers below. Each paper starts from a bounded operational question:

- When one operation crosses several control systems, what establishes that the whole operation is ready, verified and safely complete?
- When should a newly built machine image become a reusable infrastructure dependency?
- Can cost-bearing lab infrastructure be removed while portable definitions and writable node-disk state remain recoverable?
- Which record is authorised to supply a governed fact when intended, execution and observed state disagree?
- What evidence should govern recovery, service return, failback and residual state?

The papers state the claim, show the implemented boundary and provide a focused public review thread. Reviewers can assess one question without reviewing the whole repository.

## Research scope

Automation can succeed within each individual system while the wider operation remains wrong. It may act on stale authority, publish an image that has not passed a consumer test, report recovery before the service is usable, or remove an environment whose useful state cannot be restored.

HybridOps makes those cross-system decisions explicit. It separates the requested outcome from environment policy and implementation, resolves dependency order, blocks work that is not ready, publishes declared outputs, verifies the result and records the lifecycle transition. Native platforms remain authoritative for the resources they own. HybridOps governs whether the wider operation may advance from declaration to execution, verification, publication and closure.

The underlying mechanisms are established engineering practice. HybridOps implements a separate decision boundary: whether the cross-system operation may advance, publish, recover or close under its declared policy, dependency state and required observations. That runtime boundary and the public implementation used to exercise it are the contribution under review. Implementation technologies remain visible in the source maps, but they do not define the contribution.

Review should test whether this boundary addresses a recognisable operating problem, whether the implementation supports the stated behaviour and where the model fails under partial execution, recovery, authority changes, concurrency, implementation substitution or scale.

## Using the implementation maps

Each map points to three types of reference where relevant:

- **Public docs:** architecture context, reference scenarios, runbooks, and the generated blueprint catalogue.
- **Declared operations:** shipped blueprint directories that show the lifecycle declaration and its supporting files together.
- **Runtime and module source:** code that implements the relevant contract, validation, lifecycle, or evidence behaviour.

The [Blueprint Index](https://docs.hybridops.tech/platform/blueprints/) is the main catalogue for shipped operations, runbooks and source contracts. The repository [Blueprints directory](blueprints/) documents the contract model and exposes the lifecycle declarations directly.

## Published technical papers

### HybridOps Contract Runtime: Technical Review v1.1

**Question under review:** When one infrastructure operation crosses resource, configuration, platform, recovery and closure boundaries, does a separate runtime contract provide useful control over readiness, dependency state, verification and evidence?

**Paper:** https://hybridops.tech/papers/hybridops-contract-runtime-technical-review-v1.1.pdf

**Earlier edition prepared for institutional review:** https://hybridops.tech/papers/hybridops-contract-runtime-technical-review-v1.0.pdf

**Implementation map:**

- [Blueprint Index](https://docs.hybridops.tech/platform/blueprints/): catalogue of shipped operations, runbooks and source contracts.
- [Blueprint contract model](blueprints/): operating modes, intent, policy, delivery contracts, verification model and shipped operations.
- [On-Prem Authoritative Foundation](blueprints/onprem/authoritative-foundation@v1/): representative authority-gated blueprint chain.
- [`hyops blueprint` runtime](hyops/blueprint/command.py): validation, planning, preflight, deploy, rebuild, destroy, and operator guardrails.
- [`hyops` command router](hyops/cli.py): runtime command registration and command-level run-record capture.
- [Preflight protocol](https://docs.hybridops.tech/architecture/contracts/hyops-preflight-contract/): readiness and validation contract.
- [Evidence and redaction standard](https://docs.hybridops.tech/architecture/standards/evidence-and-redaction/): run-record, traceability, and redaction requirements.

**External review:** https://github.com/hybridops-tech/hybridops-core/issues/269

---

### Build, Boot, Verify, Publish v1.0

**Question under review:** What evidence should a newly built machine image satisfy before it is published as a reusable dependency, and how should that dependency later be retired?

**Paper:** https://hybridops.tech/papers/build-boot-verify-publish-v1.0.pdf

**Implementation map:**

- [Capability Map](https://docs.hybridops.tech/evidence_map/): navigation for the image and bootstrap lifecycle and related runbooks.
- [Proxmox template-image module](modules/core/onprem/template-image/): Packer-driven build, publish, clone and boot smoke validation, run-record outputs, and implementation files.
- [On-Prem RKE2 operation](blueprints/onprem/rke2@v1/): builds a template, provisions VMs, then installs RKE2.
- [Bootstrap NetBox operation](blueprints/onprem/bootstrap-netbox@v1/): uses the template build in the wider SDN, VM, PostgreSQL and NetBox chain.
- [Blueprint Index](https://docs.hybridops.tech/platform/blueprints/): other shipped operations that consume image-build steps.
- [Evidence and redaction standard](https://docs.hybridops.tech/architecture/standards/evidence-and-redaction/): persisted build, validation, and execution records.

**External review:** https://github.com/hybridops-tech/hybridops-core/issues/270

---

### Reproducible Network Training Labs v1.0

**Question under review:** Can temporary cloud or on-premises capacity provide a reproducible private lab while definitions and writable node-disk state remain recoverable after the host is removed?

**Paper:** https://hybridops.tech/papers/reproducible-network-training-labs-v1.0.pdf

**Implementation map:**

- [EVE-NG blueprint runbook](https://docs.hybridops.tech/ops/runbooks/platform/blueprints/hyops-blueprint-eve-ng/): operator workflow for the lab lifecycle.
- [EVE-NG training environment reference scenario](https://docs.hybridops.tech/reference-scenarios/eveng-lab-foundation/): design, operation, and verification in one scenario.
- [GCP EVE-NG operation](blueprints/gcp/eve-ng@v1/): creates the private GCP network and VM, installs EVE-NG and images, then runs a health check. It also supports archive and restore.
- [GCP GNS3 operation](blueprints/gcp/gns3@v1/): creates the private GCP network and VM, installs GNS3 and starter content, then runs a health check.
- [On-Prem EVE-NG operation](blueprints/onprem/eve-ng@v1/): builds from a template image, provisions the Proxmox VM, installs EVE-NG and images, then validates the host.
- [On-Prem GNS3 operation](blueprints/onprem/gns3@v1/): builds from a verified template, provisions the Proxmox VM, installs GNS3 and starter content, then validates the host.
- [Blueprint Index](https://docs.hybridops.tech/platform/blueprints/): comparative view of the on-premises and GCP lab operations.

**External review:** https://github.com/hybridops-tech/hybridops-core/issues/271

---

### Authority Before Automation v1.0

**Question under review:** When several records describe the same infrastructure fact, can an explicit authority declaration, bootstrap transfer and readiness gate prevent execution from acting on the wrong record?

**Paper:** https://hybridops.tech/papers/authority-before-automation-v1.0.pdf

**Implementation map:**

- [Authoritative on-prem foundation reference scenario](https://docs.hybridops.tech/reference-scenarios/authoritative-onprem-foundation/): source-of-truth operating model and implementation narrative.
- [Bootstrap NetBox operation](blueprints/onprem/bootstrap-netbox@v1/): builds the SDN, template, VMs, PostgreSQL and NetBox bootstrap chain.
- [Authoritative Foundation operation](blueprints/onprem/authoritative-foundation@v1/): uses NetBox-backed state to gate later platform VM expansion.
- [NetBox HA cutover operation](blueprints/onprem/netbox-ha-cutover@v1/): shows downstream state-contract consumption during service cutover.
- [Proxmox SDN operations runbook](https://docs.hybridops.tech/ops/runbooks/networking/sdn_operations/): plan, preflight, and apply path for the network foundation that feeds authoritative inventory and IPAM.
- [Blueprint Index](https://docs.hybridops.tech/platform/blueprints/): bootstrap and authoritative operations in one catalogue.

**External review:** https://github.com/hybridops-tech/hybridops-core/issues/272

---

### Recovery Operating Model v1.0

**Question under review:** Do decision, readiness, workload-verification and reverse-path gates expose enough evidence to govern recovery, failback and residual state as one operation?

**Paper:** https://hybridops.tech/papers/recovery-operating-model-v1.0.pdf

**Implementation map:**

- [PostgreSQL HA DR Cycle reference scenario](https://docs.hybridops.tech/reference-scenarios/postgresql-ha-dr-cycle/): restore to GCP, backup continuity, controlled failback, and final DNS state.
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
- whether the proposed boundary adds useful control or duplicates an existing owner
- whether the implementation and evidence support the bounded claim
- which failure, authority, concurrency, recovery or scale case would challenge it

Specific criticism and counterexamples are welcome.
