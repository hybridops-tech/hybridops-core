# Academy Moodle Storage and DR TODO

Status
- Internal planning note.
- The first Core recovery primitive candidate in this integration branch is `platform/k8s/longhorn-dr-volume`.
- Keep executable Moodle DR blueprints out of the shipped surface until cluster bring-up and DNS cutover steps are equally real.

Promotion gates for `main`
- The reusable Core primitives can merge before the full Moodle DR blueprint.
- Do not merge a Moodle-specific executable DR blueprint until:
  - the workloads repo exposes a real cloud recovery target path
  - the target cluster bootstrap path is real, not implied
  - restore drills cover workload rebind and smoke validation, not only volume restore
  - DNS cutover is gated on both PostgreSQL and Longhorn readiness

Current platform reality
- The current on-prem platform is a single server, not a clustered Proxmox estate.
- Because of that, the current resilience story is hybrid, not local-cluster HA.
- Real service continuity currently comes from:
  - durable primary file state on the on-prem site
  - backup and restore of PostgreSQL and `moodledata`
  - cloud DR provisioning
  - workload reprovisioning through Argo CD
  - DNS cutover

Resilience posture
- This is not a placeholder or lab-only posture.
- It is a valid resilience design when it is documented and operated honestly as:
  - single-site primary runtime
  - cloud DR for continuity
  - tested restore automation
- Do not describe it as zero-downtime local HA.
- Do describe it as a hybrid resilience and disaster-recovery model with explicit RTO/RPO targets.

Current Moodle storage posture
- `education-moodle-data` is now a Longhorn-backed claim in the live Stage 2 lane.
- Longhorn backup state is available in-cluster through `Backup`, `BackupVolume`, and `Volume` CRs.
- The first Core recovery primitive candidate is the Longhorn DR volume module, which can:
  - observe backup freshness and metadata
  - create standby DR volumes
  - create restore volumes
  - activate an existing standby volume
- The remaining gap is full cluster bring-up, workload rebind, and DNS cutover automation around that primitive.

Provider contract
- Kubernetes should continue to see a stable claim for `moodledata`, not provider-specific workload values.
- Current implementation:
  - stable `PersistentVolumeClaim` name: `education-moodle-data`
  - `ReadWriteOnce` access mode
  - Longhorn-backed `StorageClass`: `longhorn-moodle`
  - off-site Longhorn backup target in cloud object storage
- Keep provider-specific backup and restore controls in the platform layer, not in Moodle application values.
- Current candidate Core primitive in this branch:
  - `platform/k8s/longhorn-dr-volume`
- That primitive publishes backup freshness and restore state without baking Moodle-specific logic into Core.

Storage decision notes
- Do not present Longhorn on the current single-host platform as local HA.
- Do use Longhorn as the truthful current file-state provider because it matches the existing RKE2 and GitOps operating model.
- Keep the resilience discussion grounded in:
  - durable single-site file storage
  - strong off-site backup of `moodledata`
  - restore-driven or warm-standby cloud recovery

DR service lanes
- Baseline lane (`restore-baseline`):
  - provision cloud resources during failover
  - restore PostgreSQL
  - restore `moodledata` into cloud file storage
  - reconcile workloads
  - cut over DNS
- Enhanced lane (`warm-standby`):
  - pre-provision selected cloud dependencies
  - reduce restore or provisioning time ahead of cutover
- Keep both lanes as explicit operating profiles, not hand-wavy aspirations.

DR automation boundary
- The Moodle workload should continue to define runtime only:
  - chart/image/OIDC/ingress/secret contract
  - stable PVC interface for `moodledata`
  - backup/export contract for `moodledata`
- Core DR automation should eventually own:
  - restore sequencing
  - cloud storage hydration
  - workload bring-up
  - smoke checks
  - DNS cutover
- Do not add an executable Moodle DR blueprint until the restore path is real.

What makes this enterprise-grade
- explicit RTO and RPO targets
- off-site backups for both database and file state
- deterministic reprovisioning through GitOps
- repeatable failover and failback procedures
- decision-service gates based on backup freshness and restore readiness
- tested drills with evidence

Future options to revisit
- CephFS as the on-prem primary RWX storage plane once the platform is multi-node.
- A dedicated Moodle DR blueprint once:
  - `moodledata` backup/export exists
  - a cloud restore target exists
  - restore drills pass inside the accepted RTO
