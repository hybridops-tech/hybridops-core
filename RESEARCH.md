# Research and External Review

HybridOps Core is the public reference implementation for research exploring platform engineering, infrastructure automation, operational evidence, recovery, source-of-truth design, and reproducible infrastructure environments.

The papers below document the research and map the proposed approaches to corresponding implementation areas in HybridOps Core.

## Published research

### HybridOps Contract Runtime — Technical Review v1.0

**Paper:** https://hybridops.tech/papers/hybridops-contract-runtime-technical-review-v1.0.pdf

**Implementation areas:**
- module intent contracts
- profiles and drivers
- implementation packs
- preflight validation
- blueprints
- structured run records

**External review:** https://github.com/hybridops-tech/hybridops-core/issues/269

---

### Build, Boot, Verify, Publish v1.0

**Paper:** https://hybridops.tech/papers/build-boot-verify-publish-v1.0.pdf

**Implementation areas:**
- image and template build lifecycle
- Packer integration
- validation gates
- publication workflow
- reproducibility and evidence

**External review:** https://github.com/hybridops-tech/hybridops-core/issues/270

---

### Reproducible Network Training Labs v1.0

**Paper:** https://hybridops.tech/papers/reproducible-network-training-labs-v1.0.pdf

**Implementation areas:**
- EVE-NG and GNS3 blueprints
- disposable infrastructure
- repeatable environment provisioning
- archive and restore
- cost and lifecycle controls

**External review:** https://github.com/hybridops-tech/hybridops-core/issues/271

---

### Authority Before Automation v1.0

**Paper:** https://hybridops.tech/papers/authority-before-automation-v1.0.pdf

**Implementation areas:**
- source-of-truth architecture
- NetBox-backed infrastructure intent
- validation before execution
- authoritative state versus pipeline-generated state

**External review:** https://github.com/hybridops-tech/hybridops-core/issues/272

---

### Recovery Operating Model v1.0

**Paper:** https://hybridops.tech/papers/recovery-operating-model-v1.0.pdf

**Implementation areas:**
- recovery workflows
- structured execution evidence
- failover and failback
- environment reconstruction
- recovery validation and handoff

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
