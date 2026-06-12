# PowerDNS Shared Primary

Deploy the writable internal DNS authority on the existing Hetzner shared control host.

Outcome: PowerDNS primary serves `hyops.internal` from the shared control host and exposes the API for DNS cutover automation.

## Chain

```text
platform/network/powerdns-authority
```

See [blueprint.yml](blueprint.yml) for the full contract.

## Usage

```bash
hyops blueprint validate --ref networking/powerdns-shared-primary@v1 --blueprints-root blueprints
hyops blueprint preflight --env dev --ref networking/powerdns-shared-primary@v1 --blueprints-root blueprints
hyops blueprint deploy --env dev --ref networking/powerdns-shared-primary@v1 --blueprints-root blueprints --execute
```
