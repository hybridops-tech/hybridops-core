# platform/onprem/eve-ng

Install/configure EVE-NG on an existing **Ubuntu 22.04 (Jammy)** host via Ansible.

This module is capability-style: it **does not provision a VM**.

For new blueprints, prefer `platform/linux/eve-ng`. `platform/onprem/eve-ng` remains as the compatibility alias for older on-prem overlays and direct host inputs, including the same state-driven inventory contract used by the provider-neutral module.

HyOps validates the target OS during preflight/apply (via SSH) and fails fast if it is not Ubuntu 22.04.
Password seeding is part of the module contract: `load_vault_env` defaults to `true`, and preflight fails early if the required EVE passwords are not available from shell env or runtime vault.

Supported targeting patterns:

- direct `target_host`
- `target_state_ref` plus `target_vm_key`
- `inventory_state_ref` plus `inventory_vm_groups`

## Usage

```bash
hyops secrets ensure --env dev EVENG_ROOT_PASSWORD EVENG_ADMIN_PASSWORD

hyops apply --env dev \
  --module platform/onprem/eve-ng \
  --inputs modules/platform/onprem/eve-ng/examples/inputs.typical.yml
```

## Required Secrets

- `EVENG_ROOT_PASSWORD`
- `EVENG_ADMIN_PASSWORD`

## Outputs

- `eveng_url`
- `cap.lab.eveng = ready`
