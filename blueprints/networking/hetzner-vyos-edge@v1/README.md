# Hetzner VyOS Edge

Seed or discover a VyOS image in Hetzner, create the shared private network, and provision the routed edge pair.

Outcome: a VyOS-based Hetzner routed edge pair is available for IPsec and BGP integration.

## Chain

```text
core/shared/vyos-image-build
  -> core/hetzner/vyos-image-seed
  -> org/hetzner/shared-private-network
  -> org/hetzner/vyos-edge-foundation
```

See [blueprint.yml](blueprint.yml) for the full contract.

## Usage

```bash
hyops blueprint validate --ref networking/hetzner-vyos-edge@v1 --blueprints-root blueprints
hyops blueprint preflight --env <env> --ref networking/hetzner-vyos-edge@v1 --blueprints-root blueprints
hyops blueprint deploy --env <env> --ref networking/hetzner-vyos-edge@v1 --blueprints-root blueprints --execute
```
