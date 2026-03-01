BRIEF — Patroni PostgreSQL HA Topology (Min vs Full) + DR Overlay

Goal
- Provide a reliable “externalised PostgreSQL” foundation for HybridOps workloads.
- Support two deployment blueprints:
  1) MIN: 3 VMs (Patroni + etcd co-located) — cheapest, simplest
  2) FULL: 6 VMs (3 Postgres/Patroni + 3 dedicated etcd) — cleaner enterprise story
-: we need to add min 1 cloud async read-only replica for DR readiness.

Key Decisions
- Use Patroni for PostgreSQL HA (leader election + failover).
- Use etcd as Patroni DCS (distributed configuration store).
- etcd reliability depends more on disk latency and network stability than CPU.

Sizing Guidance
etcd node (per node, safe-minimal):
- vCPU: 1
- RAM: 1–2 GB (prefer 2 GB)
- Disk: 10–20 GB SSD

Postgres/Patroni node (per node, baseline starting point):
- vCPU: 2+
- RAM: 4–8 GB+ (scale with workload)
- Disk: SSD, sized for data + WAL + headroom.

Module (capability)
- module_ref: platform/onprem/postgresql-ha

Example Inputs (authoritative patterns)

1) MIN (3 nodes, etcd co-located)
---
topology:
  mode: colocated_dcs   # colocated_dcs | dedicated_dcs
nodes:
  postgres:
    - name: pg-01
      ip: IPAM
    - name: pg-02
      ip: IPAM
    - name: pg-03
      ip: IPAM
dcs:
  type: etcd
  colocated: true

2) FULL (6 nodes, dedicated etcd)
---
topology:
  mode: dedicated_dcs
nodes:
  postgres
    - name: pg-01
      ip: IPAM
    - name: pg-02
      ip: IPAM
    - name: pg-03
      ip: IPAM
  etcd:
    - name: etcd-01
      ip: IPAM
    - name: etcd-02
      ip: IPAM
    - name: etcd-03
      ip: IPAM
dcs:
  type: etcd
  colocated: false

3) Optional DR overlay (cloud async replica + DNS cutover parameters)
---
dr:
  enabled: true
  cloud_replica:
    provider: gcp
    name: pg-dr-01
    ip: IPAM
  dns:
    provider: cloudflare
    record: db.example.com

Meaning of MIN vs FULL
- MIN: acceptable for SME/lab; fewer VMs; simplest ops; slightly higher blast radius.
- FULL: preferred for stronger separation; more stable DCS; better enterprise narrative.
- Both can add a cloud replica later without redesigning the module contract.

Tasks
1) Implement MIN topology first (3 nodes, co-located etcd).
2) Implement FULL topology as an extension (add 3 dedicated etcd nodes).
3) Add optional DR overlay (1 cloud async replica + cutover parameters).
4) Write module README + ship example input files (min/full/dr).

Found collection that seem promising: https://galaxy.ansible.com/ui/repo/published/vitabaks/autobase/
local workspace copy may exist in a separate collections checkout for reference, but roles should be consumed from Galaxy in packaged HyOps flows (no direct edits to external role sources).
