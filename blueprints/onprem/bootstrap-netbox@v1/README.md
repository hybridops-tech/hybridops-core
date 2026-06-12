# On-Prem Bootstrap: SDN + NetBox

Bootstrap SDN, build a base template image, provision the pgcore and NetBox VMs, then configure PostgreSQL and NetBox.

Outcome: NetBox is online and ready to become authoritative IPAM and inventory.

## Chain

```text
core/onprem/network-sdn
  -> core/onprem/template-image
  -> platform/onprem/platform-vm
  -> platform/onprem/postgresql-core
  -> platform/onprem/netbox
```

See [blueprint.yml](blueprint.yml) for the full contract.

## Usage

```bash
hyops blueprint validate --ref onprem/bootstrap-netbox@v1 --blueprints-root blueprints
hyops blueprint preflight --env dev --ref onprem/bootstrap-netbox@v1 --blueprints-root blueprints
hyops blueprint deploy --env dev --ref onprem/bootstrap-netbox@v1 --blueprints-root blueprints --execute
```
