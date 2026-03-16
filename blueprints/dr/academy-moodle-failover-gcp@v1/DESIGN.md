# Academy Moodle Failover to GCP

Status
- Design contract only.
- Do not add `blueprint.yml` until the required storage restore and cloud workload modules exist.

Purpose
- Define the final boundary between:
  - the internal Moodle workload runtime contract in `hybridops-workloads-internal`
  - the future HybridOps DR blueprint that restores and cuts over the Academy Moodle lane
- Remove drift around storage by making one decision explicit:
  - on-prem primary `moodledata` uses CephFS-backed RWX storage
  - cloud DR remains restore-driven from backup artifacts, not active-active shared storage

Decision
- Primary on-prem Moodle file state must move from the current local bridge to a CephFS-backed RWX claim.
- Cloud DR must restore `moodledata` into cloud-attached file storage before the cloud Moodle workload is reconciled.
- The future DR blueprint must orchestrate restore and cutover; it must not restate Moodle chart values, OIDC settings, or application runtime details.

Current state
- The live internal Moodle lane still uses the bootstrap bridge claim `education-moodle-data`.
- That bridge is acceptable only for internal validation.
- It is not acceptable as the final production storage model or as the basis for cloud failover.

Why CephFS for on-prem primary storage
- It provides a stronger HA posture than the current local bridge and a more credible platform story than a single ad hoc NFS export.
- It fits the Academy workload need for RWX file semantics without forcing raw object storage into Moodle's live filesystem path.
- It keeps the app/runtime boundary clean:
  - image and plugin code remain immutable
  - `moodledata` remains the durable shared filesystem

Why not use Ceph as the cloud DR storage model
- The current HybridOps DR posture is restore-driven:
  - detect via Thanos
  - approve via decision service
  - provision cloud infrastructure
  - restore from backup
  - reconcile workloads
  - cut over DNS
- Extending that model into Ceph-to-Ceph cross-site storage would add unnecessary operational complexity.
- The simpler and cleaner cloud path is:
  - restore PostgreSQL from backup
  - restore `moodledata` from object backup into cloud file storage
  - reconcile the cloud Moodle workload
  - cut over `learn-lms.<domain>`

Boundary

What stays in the Moodle workload/module
- Helm chart, image, ingress, OIDC, ESO, and runtime environment contract
- PVC/storage interface only
- startup hooks needed to make the image and runtime behave correctly
- backup/export job contract for `moodledata`
- smoke checks and readiness contract

What stays out of the Moodle workload/module
- cloud failover sequencing
- cloud storage provisioning
- restore orchestration
- DNS cutover sequencing
- decision-service gating logic

What belongs in the future DR blueprint
- explicit failover gate inputs from decision-service / dispatcher
- preflight checks for backup freshness and restore eligibility
- composition with PostgreSQL DR recovery
- cloud file storage provisioning for restored `moodledata`
- restore of `moodledata` from object backup
- Argo reconciliation of the cloud Moodle target
- smoke checks against the cloud Moodle hostname
- DNS cutover for `learn-lms.<domain>`
- failback contract once on-prem storage and database state are healthy again

Anti-redundancy rule
- The future blueprint must consume:
  - the Moodle workload contract from `hybridops-workloads-internal`
  - the existing PostgreSQL DR outputs from the PostgreSQL blueprint/module chain
- It must not duplicate:
  - chart values
  - image tags
  - Keycloak/OIDC client definitions
  - Moodle application configuration

Required inputs for the future blueprint
- backup artifact reference or selector for `moodledata`
- restore target storage class / file share contract in cloud
- cloud workload target reference
- DNS routing contract for `learn-lms.<domain>`
- evidence/approval posture from decision-service / dispatcher
- PostgreSQL DR state reference or composed blueprint outputs

Expected outputs for the future blueprint
- restored cloud `moodledata` storage reference
- cloud Moodle workload target status
- smoke-check result for the cloud Moodle hostname
- DNS cutover record / state output

Decision-service gates
- Do not trigger Moodle failover on database health alone.
- Require at minimum:
  - PostgreSQL backup freshness within threshold
  - `moodledata` backup freshness within threshold
  - last restore artifact exists and is readable
  - cloud restore target prerequisites are valid
- If `moodledata` restore time exceeds the accepted DR window, move from cold restore to a warm cloud copy. Do not hide that gap in the blueprint.

Implementation path
1. Replace the local bridge claim with a CephFS-backed primary claim in the internal Moodle workload.
2. Define the `moodledata` backup/export path to cloud object storage.
3. Add the storage restore module(s) needed to hydrate cloud file storage from the backup artifact.
4. Add the executable blueprint at:
   - `blueprints/dr/academy-moodle-failover-gcp@v1/blueprint.yml`
5. Route decision-dispatcher failover records to that blueprint only after restore drills are passing.

Ceph implementation posture
- Preferred provider deployment model:
  - `cephadm`
- Use `cephadm-ansible` only as host/bootstrap automation around `cephadm`, not as the primary long-term control plane.
- Prefer an external Ceph provider cluster consumed by Kubernetes through Rook external mode / Ceph CSI rather than embedding storage lifecycle into the Moodle workload.
