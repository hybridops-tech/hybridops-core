# On-Prem VyOS Edge

Seed or discover a Proxmox VyOS template and provision a VyOS edge VM through the shared VM lifecycle.

Outcome: a VyOS edge appliance is provisioned on Proxmox with state-first template resolution and environment-prefixed VM naming.

## Chain

```text
core/onprem/vyos-template-seed
  -> platform/onprem/vyos-edge
```

See [blueprint.yml](blueprint.yml) for the full contract.

## Usage

```bash
hyops blueprint validate --ref networking/onprem-vyos-edge@v1 --blueprints-root blueprints
hyops blueprint preflight --env dev --ref networking/onprem-vyos-edge@v1 --blueprints-root blueprints
hyops blueprint deploy --env dev --ref networking/onprem-vyos-edge@v1 --blueprints-root blueprints --execute
```
