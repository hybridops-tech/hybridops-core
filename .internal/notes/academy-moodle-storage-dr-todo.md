# Academy Moodle Storage and DR TODO

Status
- Internal planning note only.
- Keep this out of the shipped blueprint surface until the storage and restore modules exist.

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
- `education-moodle-data` remains a validation bridge only.
- It is not the final production file-state path.
- The next production step is a durable single-site file-state path that fits the actual topology.
- Current preferred provider shape:
  - virtual NAS-backed NFS export for `moodledata`
- The provider may be Synology-backed today, but the workload contract must stay generic at the Kubernetes boundary.

Provider contract
- Kubernetes should see a stable claim for `moodledata`, not NAS-specific paths.
- Current intended implementation:
  - static NFS-backed `PersistentVolume`
  - stable `PersistentVolumeClaim` name: `education-moodle-data`
  - `ReadWriteMany` access mode
  - `Retain` reclaim policy
- Keep NAS host, export path, and mount options in the storage manifest layer, not in Moodle application values.
- Preferred future source of truth for those storage coordinates:
  - `platform/onprem/nfs-appliance` internal contract
  - published outputs:
    - `nfs_server`
    - `nfs_export_path`
    - `backup_profile`
- See `platform-onprem-nfs-appliance-contract.md` for the provider/module boundary.

Storage decision notes
- Do not adopt CephFS on the current single-host platform.
- Revisit CephFS only when the on-prem topology has enough nodes and failure domains to justify it.
- Until then, keep the production discussion grounded in:
  - durable single-site file storage
  - strong backup/export of `moodledata`
  - restore-driven cloud recovery

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
