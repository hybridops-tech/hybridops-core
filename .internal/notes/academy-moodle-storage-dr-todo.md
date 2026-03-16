# Academy Moodle Storage and DR TODO

Status
- Internal planning note only.
- Keep this out of the shipped blueprint surface until the storage and restore modules exist.

Current platform reality
- The current on-prem platform is a single server, not a clustered Proxmox estate.
- Because of that, real resilience currently comes from:
  - backup and restore
  - cloud DR provisioning
  - workload reprovisioning through Argo CD
  - DNS cutover
- Do not claim local storage clustering that the current hardware topology cannot support.

Current Moodle storage posture
- `education-moodle-data` remains a validation bridge only.
- It is not the final production file-state path.
- The next production step is a durable single-site file-state path that fits the actual topology.

Storage decision notes
- Do not adopt CephFS on the current single-host platform.
- Revisit CephFS only when the on-prem topology has enough nodes and failure domains to justify it.
- Until then, keep the production discussion grounded in:
  - single-site durable storage
  - strong backup/export of `moodledata`
  - restore-driven cloud recovery

DR automation boundary
- The Moodle workload should continue to define runtime only:
  - chart/image/OIDC/ingress/secret contract
  - PVC interface
  - backup/export contract for `moodledata`
- Core DR automation should eventually own:
  - restore sequencing
  - cloud storage hydration
  - workload bring-up
  - smoke checks
  - DNS cutover
- Do not add an executable Moodle DR blueprint until the restore path is real.

Future options to revisit
- CephFS as the on-prem primary RWX storage plane once the platform is multi-node.
- A dedicated Moodle DR blueprint once:
  - `moodledata` backup/export exists
  - a cloud restore target exists
  - restore drills pass inside the accepted RTO
