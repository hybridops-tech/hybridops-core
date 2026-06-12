# PowerDNS On-Prem Secondary

Provision an on-prem read-only internal DNS secondary on the shared on-prem runner host.

Outcome: an on-prem PowerDNS secondary serves replicated `hyops.internal` data for local resolution resilience.

## Chain

```text
platform/network/powerdns-authority
```

See [blueprint.yml](blueprint.yml) for the full contract.

## Usage

```bash
hyops blueprint validate --ref networking/powerdns-onprem-secondary@v1 --blueprints-root blueprints
hyops blueprint preflight --env dev --ref networking/powerdns-onprem-secondary@v1 --blueprints-root blueprints
hyops blueprint deploy --env dev --ref networking/powerdns-onprem-secondary@v1 --blueprints-root blueprints --execute
```
