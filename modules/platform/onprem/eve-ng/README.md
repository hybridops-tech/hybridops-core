# platform/onprem/eve-ng

Install/configure EVE-NG on an existing **Ubuntu 22.04 (Jammy)** host via Ansible.

This module is capability-style: it **does not provision a VM**.

HyOps validates the target OS during preflight/apply (via SSH) and fails fast if it is not Ubuntu 22.04.

## Usage

```bash
EVENG_ROOT_PASSWORD='...' \
EVENG_ADMIN_PASSWORD='...' \
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
