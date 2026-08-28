# EVE-NG on GCP

`gcp/eve-ng@v1` deploys a private EVE-NG environment on nested-virtualisation-capable GCP compute. The VM has no public address; configuration and access use IAP.

EVE-NG remains authoritative for topology and node behaviour. HybridOps manages host readiness, declared images, health verification, private access, lab preservation, reconstruction and compute release.

## Execution chain

```text
private network
  -> execution host
  -> EVE-NG configuration
  -> lab images
  -> EVE-NG health verification
```

The executable contract is [blueprint.yml](blueprint.yml). Initialise an environment copy before changing image sources, host sizing or optional licence inputs:

```bash
hyops blueprint init --env <env> --ref gcp/eve-ng@v1 --edit
```

EVE-NG credentials and authorised IOL licence content belong in the encrypted environment vault, not in the blueprint.

## Documentation

- [Operator runbook](https://docs.hybridops.tech/ops/runbooks/platform/blueprints/hyops-blueprint-eve-ng/)
- [Lifecycle and ownership](ARCHITECTURE.md)
- [Proxmox blueprint](../../onprem/eve-ng@v1/blueprint.yml)
