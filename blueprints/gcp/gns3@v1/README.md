# GNS3 on GCP

`gcp/gns3@v1` deploys an authenticated GNS3 server on private, nested-virtualisation-capable GCP compute. The VM has no public address; configuration and access use IAP.

GNS3 remains authoritative for projects, topology and node execution. HybridOps manages host readiness, declared image registration, health verification, private access, project preservation, reconstruction and compute release.

## Execution chain

```text
private network
  -> execution host
  -> GNS3 server
  -> lab images
  -> starter project
  -> GNS3 health verification
```

The executable contract is [blueprint.yml](blueprint.yml). Initialise an environment copy before changing image declarations, host sizing or optional licence inputs:

```bash
hyops blueprint init --env <env> --ref gcp/gns3@v1 --edit
```

The GNS3 server password and authorised IOU licence content belong in the encrypted environment vault.

## Documentation

- [Operator runbook](https://docs.hybridops.tech/ops/runbooks/platform/blueprints/hyops-blueprint-gns3/)
- [Lifecycle and ownership](ARCHITECTURE.md)
- [Proxmox blueprint](../../onprem/gns3@v1/blueprint.yml)
