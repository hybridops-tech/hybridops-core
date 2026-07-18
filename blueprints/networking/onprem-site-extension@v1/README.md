# On-Prem Site Extension

Extend the static Hetzner Site-A edge pair back into the on-prem VyOS edge using a dual-tunnel site-extension layer.

Outcome: the on-prem VyOS edge exchanges approved prefixes with the Hetzner edge pair inside Site-A ASN `65010`.

## Chain

```text
platform/network/vyos-site-extension-edge
  -> platform/network/vyos-site-extension-onprem
```

See [blueprint.yml](blueprint.yml) for the full contract.

## Usage

```bash
hyops blueprint validate --ref networking/onprem-site-extension@v1 --blueprints-root blueprints
hyops blueprint preflight --env <env> --ref networking/onprem-site-extension@v1 --blueprints-root blueprints
hyops blueprint deploy --env <env> --ref networking/onprem-site-extension@v1 --blueprints-root blueprints --execute
```
