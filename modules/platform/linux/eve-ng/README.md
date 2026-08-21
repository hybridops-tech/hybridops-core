# platform/linux/eve-ng

Installs and configures EVE-NG on Ubuntu 22.04 and publishes the lab-platform readiness contract used by HybridOps blueprints.

This is the provider-neutral EVE-NG capability layer. Enclosing blueprints supply the execution host and access transport, allowing the same EVE-NG contract to run across private cloud and on-premises infrastructure.

Supported access transports include:

- direct SSH
- explicit bastion or jump host
- GCP IAP SSH

Password seeding is part of the run contract:

- `load_vault_env` defaults to `true`
- validate/preflight requires `EVENG_ROOT_PASSWORD` and `EVENG_ADMIN_PASSWORD`
- private on-premises targets can resolve their bastion dynamically with `ssh_proxy_jump_auto: true`

## Usage

```bash
hyops secrets ensure --env dev EVENG_ROOT_PASSWORD EVENG_ADMIN_PASSWORD

hyops apply --env dev \
  --module platform/linux/eve-ng \
  --inputs modules/platform/linux/eve-ng/examples/inputs.min.yml
```

## Required secrets

- `EVENG_ROOT_PASSWORD`
- `EVENG_ADMIN_PASSWORD`

## Outputs

- `eveng_url`
- `cap.lab.eveng = ready`

The enclosing blueprint can combine this readiness contract with image installation, deep health checks, private UI access, topology-node automation and the EVE-NG archive/restore lifecycle.
