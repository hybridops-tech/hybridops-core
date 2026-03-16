# Blueprints

Blueprints are product-level orchestration manifests for known-good module chains.

They package repeatable outcomes, not low-level implementation details.

## Operating Modes
- `bootstrap`: Day-0 bring-up with minimal prerequisites.
- `authoritative`: Day-1+ operation where NetBox-backed IPAM/inventory is authoritative.
- `hybrid`: mixed bootstrap + authoritative flow in one chain.

## Contract Model
- `intent`: module input intent is declared per step.
- `policy`: run behavior guardrails (`fail_fast`, `evidence_required`, `ipam_authority`, `netbox_live_api_check`).
- `contracts`: per-step delivery contracts (`addressing_mode`, required upstream state).
- `verification`: probes remain module-level and evidence remains deterministic.

`netbox_live_api_check` notes:
- Default: `false` (state-based NetBox authority gate only).
- When `true`, blueprint preflight/deploy also probes live NetBox API reachability and token validity for steps that require NetBox authority/IPAM.
- Use this in environments where strict API liveness should block execution early.

## Reference Blueprints
- `onprem/bootstrap-netbox@v1`: SDN + NetBox VM bootstrap chain.
- `onprem/netbox-ha-cutover@v1`: re-point NetBox from bootstrap PostgreSQL core to PostgreSQL HA.
- `onprem/authoritative-foundation@v1`: SDN + NetBox + IPAM-gated platform VMs.
- `onprem/eve-ng@v1`: EVE-NG foundation chain with optional post-config intent.
- `networking/wan-hub-edge@v1`: Hetzner edge + GCP hub WAN baseline (network/router/HA VPN BGP).
- `networking/gcp-ops-runner@v1`: private GCP runner VM in the hub core subnet for runner-local DR/burst execution.
- `networking/onprem-ops-runner@v1`: on-prem runner VM on the management network for runner-local failback and platform execution.
- `dr/postgresql-cloudsql-standby-gcp@v1`: establish a managed Cloud SQL standby lane without traffic cutover.
- `dr/postgresql-cloudsql-promote-gcp@v1`: explicit promotion gate plus DNS cutover to the managed Cloud SQL endpoint.
- `dr/postgresql-cloudsql-failback-onprem@v1`: explicit failback gate plus DNS cutback to the on-prem PostgreSQL HA endpoint.

## Planned Internal Blueprint Designs
- `dr/academy-moodle-failover-gcp@v1`: design-only contract for internal Academy Moodle failover. This blueprint must compose existing PostgreSQL DR outputs, restore `moodledata`, sync the cloud Moodle workload target, and execute DNS cutover without duplicating Moodle runtime/chart configuration. See `blueprints/dr/academy-moodle-failover-gcp@v1/DESIGN.md`.

## CLI Usage
- Validate:
  - `hyops blueprint validate --ref onprem/bootstrap-netbox@v1 --blueprints-root blueprints`
- Preflight:
  - `hyops blueprint preflight --ref onprem/authoritative-foundation@v1 --blueprints-root blueprints --root /tmp/hyops-runtime`
- Plan:
  - `hyops blueprint plan --ref onprem/authoritative-foundation@v1 --blueprints-root blueprints`
- Deploy (execute):
  - `hyops blueprint deploy --ref onprem/authoritative-foundation@v1 --blueprints-root blueprints --execute`
- Deploy with explicit runtime root:
  - `hyops blueprint deploy --ref onprem/authoritative-foundation@v1 --blueprints-root blueprints --execute --root /tmp/hyops-runtime`

## Product Packaging Guidance
- Community: bootstrap and one authoritative expansion blueprint.
- Pro: curated multi-module chains (WAN/DR/bursting, hardened profiles, probe packs).
- Consulting: enterprise topology integration and migration blueprints.
