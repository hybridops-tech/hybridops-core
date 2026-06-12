# Edge Control Plane

Provision the edge WAN foundation, configure routing, deploy observability, and install the decision-control services used by DR and burst lanes.

Outcome: the edge control plane is ready for deterministic DR and burst signalling.

## Chain

```text
core/shared/vyos-image-build
  -> core/hetzner/vyos-image-seed
  -> org/hetzner/shared-private-network
  -> org/hetzner/vyos-edge-foundation
  -> org/gcp/wan-hub-network
  -> org/gcp/wan-cloud-router
  -> org/gcp/wan-vpn-to-edge
  -> org/hetzner/shared-control-host
  -> platform/linux/ops-runner
  -> platform/network/vyos-edge-wan
  -> platform/network/edge-observability
  -> platform/network/dns-routing
  -> platform/network/decision-service
  -> platform/network/decision-dispatcher
  -> platform/network/decision-consumer
  -> platform/network/decision-executor
```

See [blueprint.yml](blueprint.yml) for the full contract.

## Usage

```bash
hyops blueprint validate --ref networking/edge-control-plane@v1 --blueprints-root blueprints
hyops blueprint preflight --env dev --ref networking/edge-control-plane@v1 --blueprints-root blueprints
hyops blueprint deploy --env dev --ref networking/edge-control-plane@v1 --blueprints-root blueprints --execute
```
