# platform/network/wan-edge

Configure Linux WAN edge nodes (IPsec + BGP) using the `hybridops.network.wan_edge` role.

## What This Module Does

- Configures two edge hosts (`edge01`, `edge02`) with:
  - route-based IPsec tunnels (strongSwan)
  - FRR BGP peering
  - route import/export policy
- Supports state-driven inventory from `org/hetzner/wan-edge-foundation`
- Supports dependency imports from `org/gcp/wan-vpn-to-edge`

## Required Secret

- `WAN_IPSEC_PSK` (via env or vault when `load_vault_env=true`)

## Usage

```bash
hyops preflight --env <env> --strict \
  --module platform/network/wan-edge \
  --inputs "$HYOPS_CORE_ROOT/modules/platform/network/wan-edge/examples/inputs.min.yml"

hyops apply --env <env> \
  --module platform/network/wan-edge \
  --inputs "$HYOPS_CORE_ROOT/modules/platform/network/wan-edge/examples/inputs.min.yml"
```

## State Consumption

By default, this module can consume:

- `org/hetzner/wan-edge-foundation` for edge host inventory/IPs
- `org/gcp/wan-vpn-to-edge` for peer gateway + BGP tunnel IPs

You can still run it standalone by supplying explicit inputs.

## Outputs

- `cap.network.wan_edge: ready|absent`
- edge local/public peer values used for deployment

## Notes

- This module configures edge network services only.
- Infrastructure (VM creation, VPN gateway creation) remains in separate modules.
- For centralized orchestration, use blueprint `networking/wan-hub-edge@v1`.
