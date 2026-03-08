# platform/onprem/vyos-edge

Provisions VyOS routed edge appliances on Proxmox by reusing the existing generic Proxmox VM lifecycle.

This module is intentionally thin:
- it reuses the proven `platform/onprem/platform-vm` pack
- it requires a state-published VyOS template by default
- it enforces explicit VyOS cloud-init bootstrap intent

It does **not** replace day-2 route policy or tunnel automation yet. The first goal is to normalize VyOS as the default routed-edge substrate without creating a second generic VM stack.

## Usage

`hyops apply --env dev --module platform/onprem/vyos-edge --state-instance vyos_edge_vm --inputs modules/platform/onprem/vyos-edge/examples/inputs.min.yml`

Use one state slot consistently for this module in each environment. Do not mix:
- non-instance (`latest`) runs, and
- `--state-instance` runs
for the same VM names, or HyOps will block the run to prevent duplicate Proxmox VMs/IP conflicts.

## Current boundary

- Use `core/onprem/vyos-template-seed` to seed-or-discover the Proxmox template into state.
- `core/onprem/vyos-template-import` remains the manual compatibility path when the template is managed entirely outside HyOps.
- Use this module to create the VyOS VM(s).
- Put routed-edge policy, BGP, and IPsec composition into a higher-level blueprint.

## Important

Unlike generic Linux VMs, VyOS VMs must provide explicit first-boot intent via `cloud_init_user_data` and `cloud_init_meta_data`.

- `cloud_init_user_data` must contain `vyos_config_commands` or `runcmd`.
- `cloud_init_network_data` is optional; when provided it must be cloud-init v1 format (`version: 1` + `config:`).
- `cloud_init_meta_data` must include `instance-id` and `local-hostname`.

This module therefore expects a cloud-init-capable VyOS template, normally produced by `core/shared/vyos-image-build` plus `core/onprem/vyos-template-seed`. `core/shared/vyos-image-artifact` remains the registration-only compatibility path when the artifact already exists outside the default build module. It fails fast if no explicit VyOS user-data is provided.

On the current Proxmox/VyOS template path, the primary NIC enumerates as `eth0` (not `eth1`). Write bootstrap interface commands against `eth0` unless you intentionally changed interface naming in your template.

`platform/onprem/vyos-edge` requires SSH key material, but the default path is now init-driven:

- `ssh_keys_from_init: true` with `ssh_keys_init_target: proxmox` consumes the public key published by `hyops init proxmox`.
- Set explicit `ssh_keys` or `ssh_public_key` only when you intentionally override that init-discovered key.
- Placeholder values are rejected, and mixed sources of truth are rejected.
- HyOps injects the effective key set into VM cloud-init user-data for the configured `ssh_username` (default `vyos`) so key-based access remains deterministic.

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
