# Research and External Review

HybridOps Core is the public reference implementation for research exploring platform engineering, infrastructure automation, operational evidence, recovery, source-of-truth design, and reproducible infrastructure environments.

The papers below document the research and map each line of inquiry to public documentation, representative blueprint formations, and implementation source in HybridOps Core.

## How to read the implementation maps

Each map uses three kinds of references where relevant:

- **Public docs** — architecture context, reference scenarios, runbooks, and the generated blueprint catalog.
- **Blueprint formation** — the shipped blueprint README showing the ordered module chain that implements the outcome.
- **Runtime/module source** — the concrete runtime or module implementation behind the paper's claims.

The generated [Blueprint Index](https://docs.hybridops.tech/platform/blueprints/) is the catalog entry point for all shipped formations, runbooks, and source contracts. The repository-level [Blueprints README](blueprints/README.md) documents the blueprint operating modes and contract model.

## Published research

### HybridOps Contract Runtime — Technical Review v1.0

**Paper:** https://hybridops.tech/papers/hybridops-contract-runtime-technical-review-v1.0.pdf

**Implementation map:**

- [Blueprint Index](https://docs.hybridops.tech/platform/blueprints/) — generated catalog of shipped blueprint formations, runbooks, and source contracts.
- [Blueprint contract model](blueprints/README.md) — operating modes, intent, policy, delivery contracts, and verification model.
- [On-Prem Authoritative Foundation](blueprints/onprem/authoritative-foundation@v1/README.md) — representative five-step authority-gated blueprint chain.
- [`hyops blueprint` runtime](hyops/blueprint/command.py) — validation, planning, preflight, deploy, rebuild, destroy, and operator guardrails.
- [`hyops` command router](hyops/cli.py) — runtime command registration and command-level run-record capture.
- [Preflight protocol](https://docs.hybridops.tech/architecture/contracts/hyops-preflight-contract/) — published readiness and validation contract.
- [Evidence and redaction standard](https://docs.hybridops.tech/architecture/standards/evidence-and-redaction/) — run-record, traceability, and redaction requirements.

**External review:** https://github.com/hybridops-tech/hybridops-core/issues/269

---

### Build, Boot, Verify, Publish v1.0

**Paper:** https://hybridops.tech/papers/build-boot-verify-publish-v1.0.pdf

**Implementation map:**

- [Capability Map](https://docs.hybridops.tech/evidence_map/) — public navigation for the image/bootstrap lifecycle and supporting runbooks.
- [Proxmox template-image module](modules/core/onprem/template-image/README.md) — Packer-driven build, publish, clone/boot smoke validation, and run-record outputs.
- [On-Prem RKE2 formation](blueprints/onprem/rke2@v1/README.md) — template build → VM provisioning → RKE2 installation.
- [Bootstrap NetBox formation](blueprints/onprem/bootstrap-netbox@v1/README.md) — template build consumed by a wider SDN/VM/PostgreSQL/NetBox chain.
- [Blueprint Index](https://docs.hybridops.tech/platform/blueprints/) — shows other shipped formations that consume image-build steps.
- [Evidence and redaction standard](https://docs.hybridops.tech/architecture/standards/evidence-and-redaction/) — persisted build, validation, and execution records.

**External review:** https://github.com/hybridops-tech/hybridops-core/issues/270

---

### Reproducible Network Training Labs v1.0

**Paper:** https://hybridops.tech/papers/reproducible-network-training-labs-v1.0.pdf

**Implementation map:**

- [EVE-NG blueprint runbook](https://docs.hybridops.tech/ops/runbooks/platform/blueprints/hyops-blueprint-eve-ng/) — operator workflow for the governed lab lifecycle.
- [EVE-NG training environment reference scenario](https://docs.hybridops.tech/reference-scenarios/eveng-lab-foundation/) — public scenario tying design, operation, and verification together.
- [GCP EVE-NG formation](blueprints/gcp/eve-ng@v1/README.md) — private GCP network → VM → EVE-NG → images → health check, with archive/restore and lifecycle controls.
- [GCP GNS3 formation](blueprints/gcp/gns3@v1/README.md) — private GCP network → VM → GNS3 server/images/starter lab → health check.
- [On-Prem EVE-NG formation](blueprints/onprem/eve-ng@v1/README.md) — template-image → Proxmox VM → EVE-NG configuration/images/health check.
- [On-Prem GNS3 formation](blueprints/onprem/gns3@v1/README.md) — verified template → Proxmox VM → GNS3 server/images/starter lab/health check.
- [Blueprint Index](https://docs.hybridops.tech/platform/blueprints/) — comparative view of the on-prem and GCP lab formations.

**External review:** https://github.com/hybridops-tech/hybridops-core/issues/271

---

### Authority Before Automation v1.0

**Paper:** https://hybridops.tech/papers/authority-before-automation-v1.0.pdf

**Implementation map:**

- [Authoritative on-prem foundation reference scenario](https://docs.hybridops.tech/reference-scenarios/authoritative-onprem-foundation/) — public source-of-truth operating model and implementation narrative.
- [Bootstrap NetBox formation](blueprints/onprem/bootstrap-netbox@v1/README.md) — SDN → template → VMs → PostgreSQL → NetBox bootstrap chain.
- [Authoritative Foundation formation](blueprints/onprem/authoritative-foundation@v1/README.md) — NetBox-backed state gates later platform VM expansion.
- [NetBox HA cutover formation](blueprints/onprem/netbox-ha-cutover@v1/README.md) — example of downstream state-contract consumption during service cutover.
- [Proxmox SDN operations runbook](https://docs.hybridops.tech/ops/runbooks/networking/sdn_operations/) — plan/preflight/apply path for the network foundation feeding authoritative inventory/IPAM.
- [Blueprint Index](https://docs.hybridops.tech/platform/blueprints/) — documents the `authoritative` operating mode across shipped formations.

**External review:** https://github.com/hybridops-tech/hybridops-core/issues/272

---

### Recovery Operating Model v1.0

**Paper:** https://hybridops.tech/papers/recovery-operating-model-v1.0.pdf

**Implementation map:**

- [PostgreSQL HA DR Cycle reference scenario](https://docs.hybridops.tech/reference-scenarios/postgresql-ha-dr-cycle/) — recorded restore-to-GCP, backup continuity, controlled failback, and final DNS truth.
- [PostgreSQL HA backup formation](blueprints/dr/postgresql-ha-backup-gcp@v1/README.md) — GCS object repository → pgBackRest backup readiness.
- [PostgreSQL HA failover formation](blueprints/dr/postgresql-ha-failover-gcp@v1/README.md) — GCP network/VM restore path through PostgreSQL HA, backup, and DNS cutover.
- [PostgreSQL HA failback formation](blueprints/dr/postgresql-ha-failback-onprem@v1/README.md) — template/VM rebuild → restore → backup → DNS cutback.
- [GCP Ops Runner runbook](https://docs.hybridops.tech/ops/runbooks/networking/blueprints/hyops-blueprint-gcp-ops-runner/) — runner-local execution model used for DR and burst workflows.
- [Blueprint Index](https://docs.hybridops.tech/platform/blueprints/) — self-managed and managed PostgreSQL recovery formations in one catalog.
- [Evidence and redaction standard](https://docs.hybridops.tech/architecture/standards/evidence-and-redaction/) — stable non-secret execution records used to review recovery outcomes.

**External review:** https://github.com/hybridops-tech/hybridops-core/issues/273

## External review

Independent practitioners are invited to assess the published research against the corresponding public implementation.

Reviews may address:

- whether the problem reflects real operational practice
- technical credibility
- practical value
- architectural limitations
- unsupported assumptions or failure modes
- whether the implementation supports the claims made in the paper

Critical findings are as useful as positive assessments.
