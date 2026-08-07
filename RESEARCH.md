# Research and External Review

HybridOps Core provides the public implementation material for the research papers listed below. Each paper is linked to relevant documentation, blueprint formations, and source code where applicable.

## Using the implementation maps

Each map uses three types of reference:

- **Public docs:** architecture context, reference scenarios, runbooks, and the generated blueprint catalog.
- **Blueprint formations:** shipped blueprint directories that show the README, `blueprint.yml`, and related files together.
- **Runtime and module source:** the code that implements the relevant contract, validation, lifecycle, or evidence behaviour.

The [Blueprint Index](https://docs.hybridops.tech/platform/blueprints/) is the main catalog for shipped formations, runbooks, and source contracts. The repository [Blueprints directory](blueprints/) documents the contract model and exposes the formations directly.

## Published research

### HybridOps Contract Runtime: Technical Review v1.0

**Paper:** https://hybridops.tech/papers/hybridops-contract-runtime-technical-review-v1.0.pdf

**Implementation map:**

- [Blueprint Index](https://docs.hybridops.tech/platform/blueprints/): catalog of shipped blueprint formations, runbooks, and source contracts.
- [Blueprint contract model](blueprints/): operating modes, intent, policy, delivery contracts, verification model, and shipped formations.
- [On-Prem Authoritative Foundation](blueprints/onprem/authoritative-foundation@v1/): representative authority-gated blueprint chain.
- [`hyops blueprint` runtime](hyops/blueprint/command.py): validation, planning, preflight, deploy, rebuild, destroy, and operator guardrails.
- [`hyops` command router](hyops/cli.py): runtime command registration and command-level run-record capture.
- [Preflight protocol](https://docs.hybridops.tech/architecture/contracts/hyops-preflight-contract/): readiness and validation contract.
- [Evidence and redaction standard](https://docs.hybridops.tech/architecture/standards/evidence-and-redaction/): run-record, traceability, and redaction requirements.

**External review:** https://github.com/hybridops-tech/hybridops-core/issues/269

---

### Build, Boot, Verify, Publish v1.0

**Paper:** https://hybridops.tech/papers/build-boot-verify-publish-v1.0.pdf

**Implementation map:**

- [Capability Map](https://docs.hybridops.tech/evidence_map/): navigation for the image and bootstrap lifecycle and related runbooks.
- [Proxmox template-image module](modules/core/onprem/template-image/): Packer-driven build, publish, clone and boot smoke validation, run-record outputs, and implementation files.
- [On-Prem RKE2 formation](blueprints/onprem/rke2@v1/): builds a template, provisions VMs, then installs RKE2.
- [Bootstrap NetBox formation](blueprints/onprem/bootstrap-netbox@v1/): uses the template build in the wider SDN, VM, PostgreSQL, and NetBox chain.
- [Blueprint Index](https://docs.hybridops.tech/platform/blueprints/): other shipped formations that consume image-build steps.
- [Evidence and redaction standard](https://docs.hybridops.tech/architecture/standards/evidence-and-redaction/): persisted build, validation, and execution records.

**External review:** https://github.com/hybridops-tech/hybridops-core/issues/270

---

### Reproducible Network Training Labs v1.0

**Paper:** https://hybridops.tech/papers/reproducible-network-training-labs-v1.0.pdf

**Implementation map:**

- [EVE-NG blueprint runbook](https://docs.hybridops.tech/ops/runbooks/platform/blueprints/hyops-blueprint-eve-ng/): operator workflow for the lab lifecycle.
- [EVE-NG training environment reference scenario](https://docs.hybridops.tech/reference-scenarios/eveng-lab-foundation/): design, operation, and verification in one scenario.
- [GCP EVE-NG formation](blueprints/gcp/eve-ng@v1/): creates the private GCP network and VM, installs EVE-NG and images, then runs a health check. It also supports archive and restore.
- [GCP GNS3 formation](blueprints/gcp/gns3@v1/): creates the private GCP network and VM, installs GNS3 and starter content, then runs a health check.
- [On-Prem EVE-NG formation](blueprints/onprem/eve-ng@v1/): builds from a template image, provisions the Proxmox VM, installs EVE-NG and images, then validates the host.
- [On-Prem GNS3 formation](blueprints/onprem/gns3@v1/): builds from a verified template, provisions the Proxmox VM, installs GNS3 and starter content, then validates the host.
- [Blueprint Index](https://docs.hybridops.tech/platform/blueprints/): comparative view of the on-prem and GCP lab formations.

**External review:** https://github.com/hybridops-tech/hybridops-core/issues/271

---

### Authority Before Automation v1.0

**Paper:** https://hybridops.tech/papers/authority-before-automation-v1.0.pdf

**Implementation map:**

- [Authoritative on-prem foundation reference scenario](https://docs.hybridops.tech/reference-scenarios/authoritative-onprem-foundation/): source-of-truth operating model and implementation narrative.
- [Bootstrap NetBox formation](blueprints/onprem/bootstrap-netbox@v1/): builds the SDN, template, VMs, PostgreSQL, and NetBox bootstrap chain.
- [Authoritative Foundation formation](blueprints/onprem/authoritative-foundation@v1/): uses NetBox-backed state to gate later platform VM expansion.
- [NetBox HA cutover formation](blueprints/onprem/netbox-ha-cutover@v1/): shows downstream state-contract consumption during service cutover.
- [Proxmox SDN operations runbook](https://docs.hybridops.tech/ops/runbooks/networking/sdn_operations/): plan, preflight, and apply path for the network foundation that feeds authoritative inventory and IPAM.
- [Blueprint Index](https://docs.hybridops.tech/platform/blueprints/): bootstrap and authoritative formations in one catalog.

**External review:** https://github.com/hybridops-tech/hybridops-core/issues/272

---

### Recovery Operating Model v1.0

**Paper:** https://hybridops.tech/papers/recovery-operating-model-v1.0.pdf

**Implementation map:**

- [PostgreSQL HA DR Cycle reference scenario](https://docs.hybridops.tech/reference-scenarios/postgresql-ha-dr-cycle/): restore to GCP, backup continuity, controlled failback, and final DNS state.
- [PostgreSQL HA backup formation](blueprints/dr/postgresql-ha-backup-gcp@v1/): creates the GCS object repository and configures pgBackRest backup readiness.
- [PostgreSQL HA failover formation](blueprints/dr/postgresql-ha-failover-gcp@v1/): restores PostgreSQL HA in GCP and performs the DNS cutover path.
- [PostgreSQL HA failback formation](blueprints/dr/postgresql-ha-failback-onprem@v1/): rebuilds the on-prem path, restores the database, re-establishes backup, and returns DNS.
- [GCP Ops Runner runbook](https://docs.hybridops.tech/ops/runbooks/networking/blueprints/hyops-blueprint-gcp-ops-runner/): runner-local execution model used for DR and burst workflows.
- [Blueprint Index](https://docs.hybridops.tech/platform/blueprints/): self-managed and managed PostgreSQL recovery formations in one catalog.
- [Evidence and redaction standard](https://docs.hybridops.tech/architecture/standards/evidence-and-redaction/): stable non-secret execution records used to review recovery outcomes.

**External review:** https://github.com/hybridops-tech/hybridops-core/issues/273

## External review

Independent practitioners are invited to assess the papers against the corresponding public implementation.

A review may cover:

- whether the problem reflects real operational practice
- technical credibility
- practical value
- architectural limitations
- unsupported assumptions or failure modes
- whether the implementation supports the claims made in the paper

Critical findings are welcome.