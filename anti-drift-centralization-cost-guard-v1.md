# HybridOps — Centralization & Cost Guard Policy (Anti-Drift Addendum v1)

This section defines the official stance on **centralization, cost control, DR posture, and burst architecture**.

If implementation drifts from these principles without an ADR, treat it as architectural drift.

---

## 1. Core Economic Pillar

HybridOps is designed around:

- Deterministic automation
- Tarball-safe execution
- Replaceable execution packs
- Cost-aware hybrid architecture
- Evidence-driven operations

Cost efficiency is a **first-class architectural constraint**, not an afterthought.

---

## 2. Centralization Policy (v1 Baseline)

HybridOps v1 is **cost-aware by default**.

### Principle

Centralize **control signals**, not full compute planes.

### Always-On Components (Allowed)

The following may remain always-on:

- HA edge routers (Hetzner VPS pair with floating IP)
- Minimal observability aggregation (e.g., Thanos receiver / VictoriaMetrics single node)
- Decision service
- DNS automation hooks
- Evidence storage

### Not Always-On by Default

The following must NOT be always-on in cost-aware profile:

- Full Kubernetes clusters in cloud
- Always-on AKS/GKE clusters for DR
- Full duplicate app stacks
- Redundant always-on cloud databases

Cold or warm standby is preferred unless enterprise profile is explicitly selected.

---

## 3. Profiles Define Centralization Level

Centralization level is controlled by `execution.profile`.

### profile: cost-aware@v1

- On-prem cluster: always-on
- Edge HA: always-on
- Cloud clusters: provisioned on demand (burst / DR)
- DB replication: warm or backup-based
- DNS cutover: automated
- RTO: minutes (provision + restore time)

### profile: enterprise@v1

- Cloud cluster: warm standby
- DB replication: continuous
- DNS TTL: reduced
- Health checks: active
- RTO: near-zero to low minutes
- Higher recurring cost allowed

Profiles govern:
- Backend selection
- Workspace naming
- Tool versions
- Retry/timeouts
- DNS behavior
- DR policy strictness

Modules remain identical across profiles.

---

## 4. DR & Burst Model (v1 Official Shape)

### On-Prem

- RKE2 cluster (primary workload plane)
- Prometheus instance
- NetBox IPAM (bootstrap via DHCP)
- GitOps deployment via Argo CD

### Edge (Hetzner HA VPS Pair)

- IPsec/BGP termination
- Floating IP
- Thanos receiver or VictoriaMetrics single-node
- Decision service
- DNS automation component
- Optional object storage gateway

### Cloud (Azure / GCP / AWS)

- Cold cluster definition (IaC ready)
- Images pre-built and versioned
- DB backup or replication target
- Activated only when:
  - DR triggered
  - Burst threshold crossed

---

## 5. Decision Service Model (v1)

Decision service consumes:

- Aggregated metrics
- Budget thresholds
- Latency metrics
- Health probes

It produces:

- DNS cutover decision
- Cluster provisioning trigger
- Failover confirmation
- Reversion trigger

It MUST NOT:
- Directly manipulate application state
- Override ModuleSpec intent
- Bypass driver execution model

It operates at orchestration level only.

---

## 6. DNS Strategy (v1)

DNS cutover is the official failover mechanism.

Requirements:

- Automated update via provider API
- Low TTL in enterprise profile
- Safe rollback capability
- Audit trail in evidence directory

Supported future providers:

- Google DNS
- Azure DNS
- Cloudflare
- AWS Route53

Each implemented as a separate module.

---

## 7. Observability Policy

Federation is deprecated for new designs.

Preferred v1:

- Prometheus per cluster
- Remote write to central backend (VM/Thanos)
- Object storage for long-term metrics

Central backend may live on:

- Hetzner HA edge (cost-aware)
- Managed cloud service (enterprise profile)

---

## 8. Why Enterprise Centralizes

Enterprise centralized platforms exist for:

- Near-zero RTO
- Regulatory compliance
- Governance consolidation
- Operational simplicity during incidents

HybridOps supports this via `enterprise@v1` profile, not as default.

---

## 9. Anti-Drift Rules

The following constitute drift if introduced without ADR:

- Always-on cloud clusters in cost-aware profile
- Embedding backend policy into packs
- Hardcoding DNS provider logic inside modules
- Making cloud DR mandatory
- Introducing centralized cluster as default

---

# Roadmap Alignment

## Phase 1 — Foundation (Now)

- Finalize driver/profile separation
- Implement cost-aware@v1 profile
- Deploy HA Hetzner edge
- Implement Thanos or VictoriaMetrics backend
- Implement DNS cutover module
- Build minimal decision service (threshold-based)

Deliverable:
Deterministic DR drill working end-to-end.

---

## Phase 2 — Production-Ready Cost Model

- Harden decision logic (latency + budget aware)
- Add DNS provider abstraction
- Add rollback validation
- Add DR rehearsal automation
- Publish cost comparison documentation

Deliverable:
“Cost-aware hybrid DR” as product narrative.

---

## Phase 3 — Enterprise Profile

- Warm standby cluster profile
- Continuous replication DB module
- Reduced TTL cutover
- Active health checks
- Optional managed metrics backend

Deliverable:
Enterprise-grade optional upgrade tier.

---

## Phase 4 — Academy Packaging

- DR lab environment
- Burst simulation scenario
- Multi-cloud failover workshop
- Cost modeling workshop
- Observability deep dive lab

Deliverable:
Academy track aligned with real product architecture.

---

## Strategic Position

HybridOps is:

- Not a science project
- Not a hyperscale platform clone
- Not a toy homelab script

It is a:

Cost-aware, deterministic, evidence-driven hybrid platform model  
with optional enterprise-grade escalation.
