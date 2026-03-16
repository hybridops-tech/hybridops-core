# platform/onprem/nfs-appliance

Provisions Linux NFS appliance VMs on Proxmox by reusing the existing generic Proxmox VM lifecycle.

This module is intentionally thin:
- it reuses the proven `platform/onprem/platform-vm` pack
- it expects a cloud-init-capable Linux template, normally `core/onprem/template-image`
- it requires explicit first-boot NFS export bootstrap intent via cloud-init

It does not replace a future day-2 appliance configuration role. The current goal is to codify a repeatable NFS storage appliance surface on Proxmox without inventing a second VM stack or binding the product surface to a specific NAS vendor.

## Usage

`hyops apply --env dev --module platform/onprem/nfs-appliance --state-instance nfs_appliance_vm --inputs modules/platform/onprem/nfs-appliance/examples/inputs.min.yml`

Use one state slot consistently for this module in each environment. Do not mix:
- non-instance (`latest`) runs, and
- `--state-instance` runs
for the same VM names, or HyOps will block the run to prevent duplicate Proxmox VMs/IP conflicts.

## Current boundary

- Use this module to create the appliance VM and bootstrap the export on first boot.
- Use the internal workload tooling to render the Kubernetes PV/PVC contract from the appliance endpoint and export path.
- Keep vendor-specific implementation details outside the workload repo.
- Put backup/export orchestration and DR sequencing into higher-level Core automation.

## Important

Unlike a generic Linux VM, this module requires explicit cloud-init bootstrap intent for the NFS export.

- `cloud_init_user_data` must install or enable an NFS server package/service.
- `cloud_init_user_data` must define at least one export path.
- `cloud_init_user_data` must reload exports (`exportfs -ra` or equivalent).
- `cloud_init_meta_data` must include `instance-id` and `local-hostname`.

The default SSH path is init-driven:
- `ssh_keys_from_init: true` with `ssh_keys_init_target: proxmox` consumes the public key published by `hyops init proxmox`.
- Set explicit `ssh_keys` or `ssh_public_key` only when you intentionally override that init-discovered key.

## Current consumption contract

This first implementation publishes the same generic VM outputs as `platform/onprem/platform-vm`.

Use them like this until dedicated provider outputs are added:
- `NFS_SERVER`: use `outputs.nfs_server` from module state
- `NFS_EXPORT_PATH`: use `input_contract.nfs_export_path` from module state
- `NFS_MOUNT_OPTIONS`: use `input_contract.nfs_mount_options` from module state when the workload renderer supports it

That keeps the workload-side Kubernetes claim contract stable while allowing the provider module to evolve later.


## State contract

Current published state contract:
- output `nfs_server` is normalized from the appliance primary IPv4
- input contract persists:
  - `provider_kind`
  - `nfs_export_path`
  - `nfs_mount_options`
  - `snapshot_profile`
  - `backup_profile`

This is the contract the internal Moodle NFS renderer should consume.

## Example bootstrap pattern

Use cloud-init to install and export a dedicated path, for example:

```yaml
cloud_init_user_data: |
  #cloud-config
  package_update: true
  packages:
    - nfs-kernel-server
  write_files:
    - path: /etc/exports.d/hybridops-academy.exports
      permissions: '0644'
      content: |
        /srv/nfs/hybridops/academy/moodledata 10.10.40.0/24(rw,sync,no_subtree_check,no_root_squash)
  runcmd:
    - mkdir -p /srv/nfs/hybridops/academy/moodledata
    - chown nobody:nogroup /srv/nfs/hybridops/academy/moodledata
    - chmod 0775 /srv/nfs/hybridops/academy/moodledata
    - systemctl enable --now nfs-kernel-server
    - exportfs -ra
    - touch /var/lib/cloud/instance/ansible-ready
```

## Outputs

- `vms`
- `vm_ids`
- `vm_keys`
- `vm_names`
- `node_name`
- `ipv4_addresses`
- `ipv4_addresses_all`
- `mac_addresses_primary`
- `mac_addresses_all`
- `tags`
