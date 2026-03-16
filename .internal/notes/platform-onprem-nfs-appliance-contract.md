# platform/onprem/nfs-appliance Contract

Status
- Internal contract note plus current shipped thin-module boundary.
- `modules/platform/onprem/nfs-appliance` now exists as the VM/bootstrap surface.
- Dedicated provider outputs and a day-2 appliance configuration role are still future work.

Purpose
- Codify a repeatable on-prem NFS storage appliance pattern on Proxmox.
- Expose a stable provider contract to workloads and DR automation without binding the product surface to a specific NAS vendor.

Why this boundary exists
- The current implementation may be Synology-backed, but the product contract should be the storage appliance role, not the vendor brand.
- Moodle and future internal workloads need stable Kubernetes storage inputs, not appliance-specific admin details.
- DR automation needs provider outputs it can reason about during backup, restore, and cutover.

Recommended module shape
- Future shape should follow the thin-module pattern used by `platform/onprem/vyos-edge`.
- Reuse the existing generic Proxmox VM lifecycle instead of creating a second VM stack.
- Compose:
  - `platform/onprem/platform-vm` for the VM lifecycle and inventory/state
  - a future appliance configuration role for export creation, snapshots, and backup/export policy
- Do not build this as a generic workload module inside `hybridops-workloads`.

Module boundary

The current thin `platform/onprem/nfs-appliance` module owns:
- VM intent for one or more on-prem storage appliance VMs on Proxmox
- appliance bootstrap and configuration
- NFS export definition and allowed-client policy
- snapshot and backup/export profile metadata
- state-published provider outputs consumed by workload tooling and DR automation

It should not own:
- application `PersistentVolume` or `PersistentVolumeClaim` manifests
- Moodle Helm values
- cloud DR orchestration or DNS cutover
- vendor-specific UI or operational wording in the shipped product surface

Current repo reality
- `platform/onprem/platform-vm` provides the VM lifecycle baseline.
- `platform/onprem/nfs-appliance` now ships as a thin module that bootstraps the export through explicit cloud-init intent.
- The repo still does not ship a dedicated HybridOps NFS day-2 export/appliance role.
- Because of that, this note remains the place for the fuller provider contract until the configuration role and stronger publish semantics exist.

Proposed high-level inputs
- `provider_kind`
  - example values:
    - `virtual-nas`
    - `generic-linux-nfs`
- `template_state_ref`
- `template_key`
- standard VM sizing and network intent reused from the Proxmox VM module
- `exports`
  - keyed map of named exports such as `moodledata`
  - each export should define:
    - `export_path`
    - `allowed_clients`
    - optional `mount_options`
    - optional `snapshot_profile`
    - optional `backup_profile`
- `backup_profile`
  - should identify the off-site export contract, not just local snapshots
- `snapshot_profile`
  - local operational convenience only

Proposed published outputs
- `nfs_server`
- `nfs_export_path`
- `nfs_mount_options`
- `provider_kind`
- `snapshot_profile`
- `backup_profile`
- `cap.storage.nfs = ready`

These are the only outputs the workload and DR layers should depend on directly.

Workload integration contract
- Moodle should continue to consume only the stable Kubernetes claim `education-moodle-data`.
- The site-specific PV/PVC renderer should consume:
  - `NFS_SERVER <- nfs_server`
  - `NFS_EXPORT_PATH <- nfs_export_path`
- Keep all vendor-specific provider details out of the workload repo.

Current renderer target
- `hybridops-workloads-internal/.internal/tools/onprem-learn-stage2/render-moodle-nfs-storage.sh`
- That renderer already accepts:
  - `NFS_SERVER`
  - `NFS_EXPORT_PATH`
- In the current shipped module, derive `NFS_SERVER` from the appliance primary IPv4 and keep `NFS_EXPORT_PATH` aligned with the explicit export path declared in module input intent.
- Dedicated provider outputs should replace that manual mapping later.

DR integration contract
- DR automation should not care whether the provider implementation is Synology-backed or another virtual NAS form.
- DR automation should care about:
  - backup freshness
  - restore readiness
  - export coordinates needed to rebuild the workload storage contract
- Future Moodle DR orchestration should consume:
  - `backup_profile`
  - `provider_kind`
  - `cap.storage.nfs`

Composition chain
1. `core/onprem/template-image` or another approved appliance image source prepares the VM image path.
2. `platform/onprem/platform-vm` creates the appliance VM.
3. `platform/onprem/nfs-appliance` provisions the VM and bootstraps the export through explicit cloud-init intent.
4. Internal workload tooling renders the static PV/PVC set from those outputs.
5. Future DR automation consumes the same provider outputs plus backup/restore metadata.

Anti-drift rules
- Do not grow the shipped module beyond VM lifecycle and explicit bootstrap intent until the dedicated configuration role exists.
- Do not make Synology the product contract.
- Do not let workloads consume raw NAS coordinates from handwritten notes or one-off shell history.
- Do not present local snapshots as the DR authority.
