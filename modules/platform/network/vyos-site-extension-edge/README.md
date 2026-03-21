# platform/network/vyos-site-extension-edge

Configure the Hetzner VyOS edge pair for the on-prem site-extension layer.

This module is the Hetzner-side half of the Site-A extension path:

- it runs from the shared Hetzner control host
- it SSHes into `edge-a` and `edge-b`
- it configures one VTI/IPsec/BGP profile on each edge toward the on-prem VyOS

Use it together with `platform/network/vyos-site-extension-onprem`.

## What This Module Does

- resolves edge public/private addresses from `org/hetzner/vyos-edge-foundation`
- consumes a stable on-prem peer endpoint (`IPv4` or hostname/FQDN)
- configures the Hetzner edges as responders for the site-extension tunnel
- exports approved cloud-side prefixes toward on-prem
- imports only approved on-prem prefixes from the site-extension

## Dynamic-IP Note

This module exists specifically so GCP does not need to peer directly with a dynamic
on-prem public IP. The Hetzner edges remain the static public face of Site-A.

`onprem_peer_remote_address` may be:

- a fixed IPv4 address, or
- a hostname/FQDN when the on-prem public IP changes over time

## Important

If `onprem_peer_remote_address` is an IPv4 endpoint, ensure
`org/hetzner/vyos-edge-foundation` allows that source in `ipsec_source_cidrs`.

The Hetzner firewall must admit UDP `500` and `4500` from the on-prem peer
before the responder side can answer IKE.

## Required Secrets

- `SITE_EXTENSION_IPSEC_PSK`
- `WAN_EDGE_SSH_PRIVATE_KEY`

## Usage

```bash
hyops preflight --env <env> --strict \
  --module platform/network/vyos-site-extension-edge \
  --inputs "$HYOPS_CORE_ROOT/modules/platform/network/vyos-site-extension-edge/examples/inputs.state.yml"

hyops apply --env <env> \
  --module platform/network/vyos-site-extension-edge \
  --inputs "$HYOPS_CORE_ROOT/modules/platform/network/vyos-site-extension-edge/examples/inputs.state.yml"
```

## State Consumption

- `org/hetzner/shared-control-host#edge_control_host`
- `org/hetzner/vyos-edge-foundation`
- `org/gcp/wan-hub-network` for cloud subnet ranges exported toward on prem

State driven cloud prefix note:

- when `auto_include_cloud_*_in_advertise` inputs are enabled, the module dedupes the
  effective `advertise_prefixes` set from `org/gcp/wan-hub-network` outputs and any
  explicit prefixes you still provide
- enable the pod secondary range for GKE burst lanes so on prem systems can return
  traffic directly to burst pods

## Outputs

- `onprem.peer_remote_address`
- `vyos.edge01.bgp_neighbor`
- `vyos.edge02.bgp_neighbor`
- `cap.network.vyos_site_extension_edge: ready|absent`
