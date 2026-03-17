# platform/gcp/platform-vm

Provision one or more generic GCP Compute Engine VMs via Terragrunt/Terraform.

This module is infrastructure-only:

- It does **not** configure services on the VM (pair with `config/ansible` modules).
- It does **not** manage firewall rules (bring your own network policy).

It can also enable nested virtualization for workloads that need KVM in the guest, such as EVE-NG.

## Prereqs

- `hyops init gcp --env <env>` completed (writes runtime credentials tfvars).
- You have selected a `zone` and network/subnet.
- Preferred for multi-project environments: consume `project_id` and VPC/subnet names from upstream state via
  `project_state_ref` and `network_state_ref` instead of duplicating them in each VM overlay.

## State-driven cloud coordinates

`platform/gcp/platform-vm` supports the same state-driven contract style as other GCP modules:

- `project_state_ref`: resolves `inputs.project_id`
- `network_state_ref`: resolves `inputs.network`
- `subnetwork_output_key`: resolves `inputs.subnetwork` from a named output published by the network state
- `ssh_keys_from_init`: resolves `inputs.ssh_keys` from `<root>/meta/gcp.ready.json` so blueprints do not need to embed a public key

SSH key source of truth is intentionally strict:

- use explicit `ssh_keys`, or
- use `ssh_keys_from_init: true`

Do not set both in the same input file. HybridOps now fails fast if both are present.

Fresh cloud VMs can also be gated before downstream steps consume them:

- `post_apply_ssh_readiness: true`, or
- `post_apply_ssh_readiness: { ... }`

Use this when a blueprint creates GCP VMs and immediately hands off to an Ansible/config module. That keeps the
handoff one-pass and avoids racing the guest boot/SSH availability window.

For private GCP VMs, the readiness probe now uses the VM's GCP instance identity for IAP-aware SSH checks by
default. It does not inherit an unrelated bastion/proxy path unless you set one explicitly in
`post_apply_ssh_readiness`. When that path is used, the VM must be reachable through the network policy that
permits IAP TCP forwarding. In the shipped WAN-hub pattern, that normally means including the `allow-iap-ssh`
tag on the target VM or providing an explicit proxy jump instead.

Example:

```yaml
project_state_ref: org/gcp/project-factory
network_state_ref: org/gcp/wan-hub-network
subnetwork_output_key: subnet_workloads_name
zone: europe-west2-a
ssh_username: opsadmin
ssh_keys_from_init: true
post_apply_ssh_readiness:
  enabled: true
  required: true
  target_user: opsadmin
  connectivity_wait_s: 180
vms:
  app-01:
    role: app
```

This keeps cloud VM blueprints DRY and env-scoped:

- project identity comes from the selected `--env` state
- network/subnet selection comes from the selected `--env` state
- reruns do not depend on copied/transient `work/` files
- public key material stays env-scoped in runtime init metadata instead of being baked into shipped blueprint files

The Terraform pack also sets `allow_stopping_for_update = true` on the compute instance resources. That keeps
state-driven project/network corrections from failing when GCE requires a stop/start cycle to apply an in-place
instance update.
## Nested Virtualization

Set `enable_nested_virtualization: true` at the module level or per VM when the guest will run nested workloads.

Example:

```yaml
zone: europe-west2-a
enable_nested_virtualization: true
vms:
  eve-ng-01:
    role: eve-ng
```

## Usage

```bash
hyops preflight --env dev --strict \
  --module platform/gcp/platform-vm \
  --inputs "$HYOPS_CORE_ROOT/modules/platform/gcp/platform-vm/examples/inputs.min.yml"

hyops apply --env dev \
  --module platform/gcp/platform-vm \
  --inputs "$HYOPS_CORE_ROOT/modules/platform/gcp/platform-vm/examples/inputs.min.yml"
```

## Outputs

This module publishes a `vms` map suitable for consumption via `inventory_state_ref` in Ansible modules:

- `outputs.vms.<vm_key>.ipv4_address` (preferred for inventory)
- `outputs.vms.<vm_key>.ipv4_configured_primary` (internal IP)
