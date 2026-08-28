# EVE-NG on Proxmox

`onprem/eve-ng@v1` builds a verified Ubuntu 22.04 template, provisions an EVE-NG VM on Proxmox, configures the lab service, installs declared images and verifies health.

EVE-NG remains authoritative for topology and node behaviour. HybridOps manages the template and VM lifecycle, private access, lab preservation and reconstruction.

## Execution chain

```text
template image
  -> execution host
  -> EVE-NG configuration
  -> lab images
  -> EVE-NG health verification
```

The executable contract is [blueprint.yml](blueprint.yml). Initialise an environment copy before changing Proxmox settings, image sources or optional licence inputs:

```bash
hyops blueprint init --env <env> --ref onprem/eve-ng@v1 --edit
```

The target bridge must provide VM connectivity. EVE-NG credentials and authorised IOL licence content belong in the encrypted environment vault.

## Documentation

- [Operator runbook](https://docs.hybridops.tech/ops/runbooks/platform/blueprints/hyops-blueprint-eve-ng/)
- [GCP blueprint](../../gcp/eve-ng@v1/blueprint.yml)
