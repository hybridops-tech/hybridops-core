# platform/network/vyos-site-extension-onprem

Configure the on-prem VyOS edge as the initiator side of the Site-A extension.

This module is the on-prem half of the Hetzner-backed site-extension path:

- it runs on `localhost` (workstation or runner)
- it SSHes directly into the on-prem VyOS edge
- it configures two peers, one to `edge-a` and one to `edge-b`

Use it together with `platform/network/vyos-site-extension-edge`.

## What This Module Does

- resolves the on-prem VyOS target from `platform/onprem/vyos-edge#vyos_edge_vm`
- resolves Hetzner edge public IPs from `org/hetzner/vyos-edge-foundation`
- configures the on-prem VyOS as the initiator side
- optionally installs static routes for internal prefixes that must be originated into BGP
- exports approved on-prem prefixes and imports only approved cloud-side prefixes

## Important

If you advertise internal prefixes that are not already present in the on-prem VyOS
routing table, set:

- `static_route_prefixes`
- `internal_route_next_hop`

That keeps route origination explicit and avoids guessing hidden topology.

If the Hetzner public peer IPs do not resolve out the same uplink as
`onprem_bind_interface`, set:

- `public_peer_route_next_hop`

That installs explicit `/32` routes for the public peers so the site-extension
initiator leaves through the intended WAN path instead of a management/default
route.

## Required Secrets

- `SITE_EXTENSION_IPSEC_PSK`
- `ONPREM_EDGE_SSH_PRIVATE_KEY`

Seed the SSH key from a file rather than inline shell quoting:

```bash
hyops secrets set --env <env> \
  --from-file ONPREM_EDGE_SSH_PRIVATE_KEY=~/.ssh/id_ed25519
```

## Usage

```bash
hyops preflight --env <env> --strict \
  --module platform/network/vyos-site-extension-onprem \
  --inputs "$HYOPS_CORE_ROOT/modules/platform/network/vyos-site-extension-onprem/examples/inputs.state.yml"

hyops apply --env <env> \
  --module platform/network/vyos-site-extension-onprem \
  --inputs "$HYOPS_CORE_ROOT/modules/platform/network/vyos-site-extension-onprem/examples/inputs.state.yml"
```

## State Consumption

- `platform/onprem/vyos-edge#vyos_edge_vm`
- `org/hetzner/vyos-edge-foundation`

## Outputs

- `onprem.target_host`
- `vyos.edge01.bgp_neighbor`
- `vyos.edge02.bgp_neighbor`
- `cap.network.vyos_site_extension_onprem: ready|absent`
