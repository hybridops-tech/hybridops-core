# platform/network/vyos-edge-wan

Configure VyOS WAN day-2 policy (IPsec + BGP) on Hetzner edge peers from a shared control host.

This module is the product path for routed-edge policy on VyOS.
It intentionally replaces the legacy Linux strongSwan/FRR `platform/network/wan-edge` path.

## What This Module Does

- Connects to a shared control host inventory target (`edge_control` group)
- From that control host, SSHes into edge peers (`edge01`, `edge02`)
- Validates edge SSH reachability from the control host before any config apply.
- Applies deterministic VyOS config for:
  - route-based IPsec peers to GCP HA VPN
  - VTI interfaces with inside /30 addresses
  - BGP peering and route policy

## Required Secret

- `WAN_IPSEC_PSK` (via env or vault when `load_vault_env=true`)
- SSH key source for control-host -> VyOS access:
  - preferred: `WAN_EDGE_SSH_PRIVATE_KEY` env (transient, module writes/removes temp key on control host), or
  - fallback: key file present on control host at `vyos_ssh_key_file`

## Usage

```bash
hyops preflight --env <env> --strict \
  --module platform/network/vyos-edge-wan \
  --inputs "$HYOPS_CORE_ROOT/modules/platform/network/vyos-edge-wan/examples/inputs.state.yml"

hyops apply --env <env> \
  --module platform/network/vyos-edge-wan \
  --inputs "$HYOPS_CORE_ROOT/modules/platform/network/vyos-edge-wan/examples/inputs.state.yml"
```

## State Consumption

By default this module can consume:

- `org/hetzner/vyos-edge-foundation` for edge public/private addresses
- `org/gcp/wan-vpn-to-edge` for peer public addresses and BGP inside IPs

The control host inventory should usually come from:

- `org/hetzner/shared-control-host#edge_control_host`

## Outputs

- `vyos.edge01.peer_ip`
- `vyos.edge02.peer_ip`
- `vyos.edge01.bgp_neighbor`
- `vyos.edge02.bgp_neighbor`
- `cap.network.vyos_edge_wan: ready|absent`
