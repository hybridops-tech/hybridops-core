# On-Prem Authoritative Foundation

Bring up the day-1 on-prem foundation where NetBox-backed state gates IPAM-driven platform VM expansion.

Outcome: subsequent platform services provision from authoritative NetBox-backed intent.

## Chain

```text
core/onprem/network-sdn
  -> platform/onprem/netbox
  -> platform/onprem/platform-vm
  -> platform/onprem/postgresql-core
  -> platform/onprem/platform-vm
```

See [blueprint.yml](blueprint.yml) for the full contract.

## Usage

```bash
hyops blueprint validate --ref onprem/authoritative-foundation@v1 --blueprints-root blueprints
hyops blueprint preflight --env dev --ref onprem/authoritative-foundation@v1 --blueprints-root blueprints
hyops blueprint deploy --env dev --ref onprem/authoritative-foundation@v1 --blueprints-root blueprints --execute
```
