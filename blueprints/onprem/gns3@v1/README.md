# GNS3 on Proxmox

`onprem/gns3@v1` builds a verified Ubuntu 22.04 template, provisions a dedicated GNS3 VM on Proxmox, configures the authenticated server, registers declared images and verifies health.

GNS3 remains authoritative for projects, topology and node execution. HybridOps manages the template and VM lifecycle, private access, project preservation and reconstruction.

## Execution chain

```text
template image
  -> execution host
  -> GNS3 server
  -> lab images
  -> starter project
  -> GNS3 health verification
```

The executable contract is [blueprint.yml](blueprint.yml). Initialise an environment copy before changing Proxmox settings, images or optional licence inputs:

```bash
hyops blueprint init --env <env> --ref onprem/gns3@v1 --edit
```

The target bridge must provide VM connectivity. The GNS3 server password and authorised IOU licence content belong in the encrypted environment vault.

## Documentation

- [Operator runbook](https://docs.hybridops.tech/ops/runbooks/platform/blueprints/hyops-blueprint-gns3/)
- [GCP blueprint](../../gcp/gns3@v1/blueprint.yml)
