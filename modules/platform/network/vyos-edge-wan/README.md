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

Baseline routing note:

- Keep `advertise_prefixes: []` for the initial GCP <-> Hetzner underlay.
- Only add spoke or on-prem prefixes after those routes actually exist on the edge.
- Do not advertise future prefixes speculatively just to make Cloud Router show learned routes.

Convergence note:

- Cloud VPN/BGP convergence on one edge can lag the other during day-2 reruns.
- The default post-apply convergence window is intentionally longer than the initial
  underlay bring-up so HyOps does not report a false failure while the slower leg
  finishes re-establishing.

## Required Secrets

- `WAN_IPSEC_PSK` (via env or vault when `load_vault_env=true`)
- `WAN_EDGE_SSH_PRIVATE_KEY` for reproducible control-host -> edge access
- SSH key source for control-host -> VyOS access:
  - preferred: `WAN_EDGE_SSH_PRIVATE_KEY` env (transient, module writes/removes temp key on control host), or
  - fallback: key file present on control host at `vyos_ssh_key_file`

For shipped/reusable runs, keep both env keys in `required_env` so HyOps can
reconstruct access from vault without relying on manual controller state. Only
remove `WAN_EDGE_SSH_PRIVATE_KEY` from `required_env` if you deliberately manage
`vyos_ssh_key_file` out of band on the control host.

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
- `org/gcp/wan-hub-network` for cloud subnet ranges such as the GKE pod secondary range

The control host inventory should usually come from:

- `org/hetzner/shared-control-host#edge_control_host`

State driven cloud prefix note:

- when `auto_include_cloud_*` inputs are enabled, the module dedupes the effective
  `import_allow_prefixes` set from `org/gcp/wan-hub-network` outputs and any explicit
  prefixes you still provide
- this is the correct path for GKE burst lanes because pod egress to on prem systems
  requires the pod secondary range to be routable back through the site extension

Firewall dependency note:

- This module now consumes `ipsec_source_cidrs` from `org/hetzner/vyos-edge-foundation`
  when that state is available.
- If the current GCP HA VPN public IPs (`edge01_peer_public_ip` / `edge02_peer_public_ip`)
  are not included in that allowlist, validation fails before any VyOS day-2 changes are applied.
- This prevents false day-2 churn when the real issue is a stale Hetzner firewall policy.

## Outputs

- `vyos.edge01.peer_ip`
- `vyos.edge02.peer_ip`
- `vyos.edge01.bgp_neighbor`
- `vyos.edge02.bgp_neighbor`
- `cap.network.vyos_edge_wan: ready|absent`
