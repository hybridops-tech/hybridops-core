# platform/linux/eve-ng

Install and configure EVE-NG on a single **Ubuntu 22.04 (Jammy)** Linux host.

This module is the provider-neutral EVE-NG capability layer used by both on-prem and cloud blueprints. It does **not** provision a VM by itself.

Supported access modes:
- direct SSH
- explicit bastion / jump host
- GCP IAP SSH

For new blueprints, prefer `platform/linux/eve-ng`. The older `platform/onprem/eve-ng` module remains for compatibility with existing inputs.

HybridOps now treats password seeding as part of the safe run contract:
- `load_vault_env` defaults to `true`
- validate/preflight fail early if `EVENG_ROOT_PASSWORD` and `EVENG_ADMIN_PASSWORD` are not seeded
- on-prem private targets can use `ssh_proxy_jump_auto: true`, which defers bastion resolution to runtime preflight instead of timing out on direct SSH

## Usage

```bash
hyops secrets ensure --env dev EVENG_ROOT_PASSWORD EVENG_ADMIN_PASSWORD

hyops apply --env dev \
  --module platform/linux/eve-ng \
  --inputs modules/platform/linux/eve-ng/examples/inputs.min.yml
```

## Required Secrets

- `EVENG_ROOT_PASSWORD`
- `EVENG_ADMIN_PASSWORD`

## Outputs

- `eveng_url`
- `cap.lab.eveng = ready`

For the current EVE role, `eveng_url` is published as `http://...` unless you terminate TLS separately in front of the host.
