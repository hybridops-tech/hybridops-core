# platform/gcp/platform-vm

Provision one or more generic GCP Compute Engine VMs via Terragrunt/Terraform.

This module is infrastructure-only:

- It does **not** configure services on the VM (pair with `config/ansible` modules).
- It does **not** manage firewall rules (bring your own network policy).

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

Example:

```yaml
project_state_ref: org/gcp/project-factory
network_state_ref: org/gcp/wan-hub-network
subnetwork_output_key: subnet_workloads_name
zone: europe-west2-a
ssh_username: opsadmin
ssh_keys_from_init: true
vms:
  app-01:
    role: app
```

This keeps cloud VM blueprints DRY and env-scoped:

- project identity comes from the selected `--env` state
- network/subnet selection comes from the selected `--env` state
- reruns do not depend on copied/transient `work/` files
- public key material stays env-scoped in runtime init metadata instead of being baked into shipped blueprint files

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
