# WAN Hub to Edge

Provision Hetzner VyOS edge peers, GCP hub networking, and HA VPN with BGP between the cloud hub and routed edge.

Outcome: deterministic BGP and IPsec control plane between GCP Cloud Router and Hetzner VyOS edge peers.

## Chain

```text
core/shared/vyos-image-build
  -> core/hetzner/vyos-image-seed
  -> org/hetzner/vyos-edge-foundation
  -> org/gcp/wan-hub-network
  -> org/gcp/wan-cloud-router
  -> org/gcp/wan-vpn-to-edge
```

See [blueprint.yml](blueprint.yml) for the full contract.

## Usage

```bash
hyops blueprint validate --ref networking/wan-hub-edge@v1 --blueprints-root blueprints
hyops blueprint preflight --env dev --ref networking/wan-hub-edge@v1 --blueprints-root blueprints
hyops blueprint deploy --env dev --ref networking/wan-hub-edge@v1 --blueprints-root blueprints --execute
```
