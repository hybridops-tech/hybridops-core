# platform/onprem/platform-vm

Creates or converges generic Proxmox VMs for custom platform workloads.

## Usage
`hyops deploy --module platform/onprem/platform-vm --inputs modules/platform/onprem/platform-vm/examples/inputs.typical.yml`

Supports:
- single VM shorthand (`vm_name`, optional `vm_id`, `vm_ipv4_cidr`, `vm_gateway`, `vm_mac`)
- multi-VM mode via `vms` map (minimum one VM)
- state-first template resolution via `template_state_ref` (optional `template_key`)
- image templates from `core/onprem/template-image` outputs
- authoritative IPAM enforcement by default (`require_ipam: true`)
- post-apply SSH readiness gate by default (fails `platform-vm` apply before downstream modules when Linux VMs never become reachable)
- export/sync hook to NetBox inventory by default (non-strict; auto-skips before NetBox is ready)

## Inputs
- `examples/inputs.min.yml` smallest practical overlay.
- `examples/inputs.typical.yml` common multi-VM overlay.
- `examples/inputs.enterprise.yml` advanced multi-VM override.
- Shipped overlays are IPAM-first (bridge-only interfaces, no hardcoded per-VM IPv4 literals).

Defaults remain in `spec.yml`; overlays are preferred for customization.

Template behavior:
- If `template_state_ref` is set, preflight resolves `template_vm_id` from env state before provider calls.
- `build_image: true` is not supported; the module fails fast when this flag is set.

VM naming (multi-env on one Proxmox cluster):
- HybridOps keeps logical VM keys stable (`inputs.vms` keys such as `pgha-01`, `rke2-cp-01`) for state, inventory groups, and blueprint contracts.
- Physical Proxmox VM display names are env-scoped by default to avoid collisions on shared metal.
- Prefix precedence for physical names:
  - `inputs.name_prefix`
  - `inputs.context_id`
  - runtime `--env` (via `HYOPS_ENV`)
- Examples:
  - `dev-pgha-01`, `staging-pgha-01`, `prod-pgha-01`
- NetBox export/sync uses the physical VM name emitted by Terraform, so NetBox VM names stay distinct across envs too.
- Advanced per-VM override (exact physical name): set `inputs.vms.<logical_name>.vm_name`.

IPAM enforcement:
- By default, `require_ipam=true` forces `inputs.addressing.mode=ipam` and `inputs.addressing.ipam.provider=netbox`.
- In IPAM mode, apply/preflight fails fast when NetBox authority state is not ready.
- In IPAM mode, HybridOps also reads `core/onprem/network-sdn` from the SDN authority (default: `--env shared`) to map `bridge -> subnet` for allocations.
- In IPAM mode, interfaces without explicit `ipv4.address` are allocated from NetBox IPAM.
- IP allocation is identity-based: HybridOps reserves by a stable NetBox IP description key (`zone + logical_vm_name + bridge + nic_index`) and reuses that reservation on re-apply when the IP record still exists.
- NetBox IPAM prevents duplicate allocations/conflicts; if a prior reservation is still present, HybridOps will not allocate the same IP to another VM.
- In IPAM mode, ensure `NETBOX_API_TOKEN` is present for the target env (`hyops secrets ensure --env <env> NETBOX_API_TOKEN`).
- For day-0 bootstrap only, override with `require_ipam: false` and explicit static interface IPs.
- Bridge alias `vnetenv` is supported for workload blueprints and resolves from `--env`:
  - `dev` -> `vnetdev`
  - `staging`/`stage` -> `vnetstag`
  - `prod` -> `vnetprod`
- Bridge alias `vnetenvdata` is supported for env-specific data tiers and resolves from `--env`:
  - `dev` -> `vnetddev`
  - `staging`/`stage` -> `vnetdstg`
  - `prod` -> `vnetdprd`
  - For other envs (for example `shared`), use an explicit bridge such as `vnetmgmt` or `vnetdata`.

SDN authority overrides (advanced):
- `HYOPS_SDN_AUTHORITY_ENV=<env>` to read SDN state from another HybridOps env (default: `shared`)
- `HYOPS_SDN_AUTHORITY_ROOT=/path/to/runtime/root` to pin an explicit authority root

Static-on-SDN safety:
- Even when `require_ipam=false`, runs targeting HybridOps SDN bridges (`vnet*`) fail fast if the SDN authority state is missing/not ready.

VM-set collision guard:
- Preflight/apply compares requested VM names with existing managed names in the same module state.
- If they differ, run fails fast to prevent accidental destructive replacement.
- Only set `allow_vm_set_replace: true` when replacement is explicitly intended.

Post-apply SSH readiness:
- `platform-vm` apply runs a built-in SSH readiness probe against provisioned Linux VMs after Terragrunt apply completes.
- Default behavior is `required: true` (provisioning fails fast if SSH never comes up).
- The gate reuses HybridOps bastion/proxy logic and can auto-use the Proxmox host (`ssh_proxy_jump_auto`) when the runner is not routed to the VM network.
- Tune or disable with:

```yaml
post_apply_ssh_readiness:
  enabled: true                 # default
  required: true                # default (fail provisioning if SSH not ready)
  connectivity_timeout_s: 5     # per-attempt TCP/SSH timeout
  connectivity_wait_s: 300      # total wait budget after apply
  # target_user: "opsadmin"     # defaults to inputs.ssh_username or opsadmin
  # ssh_proxy_jump_auto: true   # default
```

Evidence:
- `post_apply_ssh_readiness.json`
- `connectivity_proxy_nc.*` / `connectivity_ssh_auth.*` (when probes run)

NetBox export/sync hook (default, non-strict):
- `platform-vm` apply exports a VM dataset and attempts NetBox sync when authority state + token are available.
- Before NetBox is ready (for example day-0 bootstrap), the hook emits a warning and continues.
- When the VM dataset references a NetBox virtualization cluster (for example `onprem-core`) that does not yet exist, HybridOps auto-creates the cluster and a default cluster type (`hyops-managed`) during sync.
- VM sync also enriches NetBox VM/interface records from the dataset when available:
  - VM sizing (`vcpus`, `memory`, `disk`)
  - interface MAC address
  - provider linkage via `external_id` custom field (auto-created by default on first sync; falls back safely if NetBox API schema blocks auto-create)
  - VM role (auto-creates NetBox device role if dataset includes `role`)
- Optional overrides for cluster type auto-create:
  - `NETBOX_CLUSTER_AUTO_CREATE=false` to disable auto-create
  - `NETBOX_CLUSTER_TYPE_ID=<id>` to use an existing NetBox cluster type
  - `NETBOX_CLUSTER_TYPE_NAME` / `NETBOX_CLUSTER_TYPE_SLUG` to control the auto-created type
  - `NETBOX_VM_ROLE_COLOR=<hex>` to control auto-created VM role color
  - `NETBOX_VM_EXTERNAL_ID_FIELD=<field_name>` to use a custom-field name other than `external_id`
  - `NETBOX_VM_EXTERNAL_ID_CF_AUTO_CREATE=false` to disable custom-field auto-create
- Evidence includes `hook_export_infra.json` and `hook_netbox_sync.json` when sync runs.
- Destroy path sync:
  - `platform-vm` destroy now runs a NetBox VM destroy-sync using the module's last state (before it is marked destroyed).
  - Default behavior is enterprise-safe soft-retire (mark VMs `offline` + stale tag) rather than hard delete.
  - Opt-in hard delete: set `HYOPS_NETBOX_SYNC_DESTROY_HARD_DELETE=true` before destroy.

Use this module as generic VM infrastructure. Service composition belongs in blueprints.
