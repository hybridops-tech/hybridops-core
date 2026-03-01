# wan_edge

Configure Linux as a WAN edge device with route-based IPsec VPN and BGP routing.

## Overview

Deploys strongSwan (swanctl) for IPsec, VTI interfaces for route-based tunnels, and FRR for BGP dynamic routing. Designed for hybrid cloud connectivity patterns such as site-to-cloud VPN with GCP HA VPN or Azure VPN Gateway.

## Requirements

- Debian 11+ or Ubuntu 22.04+
- Root/sudo access
- Network interfaces for tunnel endpoints (separate from management recommended)

## Role Variables

### Required

| Variable | Description |
|----------|-------------|
| `wan_public_local_ip` | Local public IP for IPsec endpoints |
| `wan_public_peer_ip` | Default remote peer IP |
| `wan_tunnels` | List of tunnel definitions (see below) |
| `wan_ipsec.psk` | Pre-shared key for IKE authentication |
| `wan_bgp.local_as` | Local BGP autonomous system number |
| `wan_bgp.peer_as` | Remote BGP autonomous system number |
| `wan_bgp.router_id` | BGP router ID |
| `wan_bgp.neighbors` | List of BGP neighbor IPs (tunnel inside IPs) |
| `wan_bgp.advertise` | Prefixes to advertise via BGP |
| `wan_bgp.import_allow` | Prefixes to accept from peer |
| `wan_bgp.export_allow` | Prefixes permitted for export |

### Tunnel Definition

```yaml
wan_tunnels:
  - name: tunnel_a
    ifname: vti10
    key: 10
    mark: 10
    inside_local: "169.254.10.1/30"
    inside_peer: "169.254.10.2"
    peer_public_ip: "203.0.113.1"      # optional, overrides wan_public_peer_ip
    local_public_ip: "198.51.100.1"    # optional, overrides wan_public_local_ip
```

### Optional

| Variable | Default | Description |
|----------|---------|-------------|
| `wan_pub_if` | auto-detected | Interface for tunnel endpoints |
| `wan_public_aliases` | `[]` | Additional IPs to assign to tunnel interface |
| `wan_loopbacks` | `[]` | Loopback addresses for routing |
| `wan_ipsec.proposals` | `aes256-sha256-modp2048` | IKE proposals |
| `wan_ipsec.esp_proposals` | `aes256-sha256` | ESP proposals |
| `wan_ipsec.start_action` | `start` | Tunnel initiation behavior |
| `wan_ipsec.dpd_delay` | `30s` | Dead peer detection interval |
| `wan_ipsec.dpd_timeout` | `120s` | DPD timeout |

## Example Playbook

```yaml
- name: Configure WAN edge
  hosts: edge
  roles:
    - role: hybridops.network.wan_edge
```

## Example Inventory

```yaml
# group_vars/edge.yml
wan_pub_if: "eth1"
wan_public_local_ip: "198.51.100.10"
wan_public_peer_ip: "203.0.113.10"

wan_loopbacks:
  - "10.110.0.1/24"

wan_tunnels:
  - name: tunnel_a
    ifname: vti10
    key: 10
    mark: 10
    inside_local: "169.254.10.1/30"
    inside_peer: "169.254.10.2"

  - name: tunnel_b
    ifname: vti11
    key: 11
    mark: 11
    inside_local: "169.254.10.5/30"
    inside_peer: "169.254.10.6"
    peer_public_ip: "203.0.113.11"

wan_ipsec:
  psk: "{{ vault_wan_ipsec_psk }}"
  start_action: "start"
  proposals: "aes256-sha256-modp2048"
  esp_proposals: "aes256-sha256"
  dpd_delay: "30s"
  dpd_timeout: "120s"

wan_bgp:
  local_as: 65010
  peer_as: 64514
  router_id: "10.110.0.1"
  neighbors:
    - "169.254.10.2"
    - "169.254.10.6"
  advertise:
    - "10.110.0.0/24"
  import_allow:
    - "10.70.0.0/20"
  export_allow:
    - "10.110.0.0/24"
```

## Architecture

```
                    IPsec (ESP)
  [Edge Site] ←─────────────────────→ [Cloud VPN Gateway]
      │                                      │
   vti10/vti11                          Cloud Router
      │                                      │
   FRR BGP ←─── BGP over tunnel ───→    BGP peering
      │                                      │
  10.110.0.0/24                         10.70.0.0/20
```

## Traffic Selectors

The role configures narrow traffic selectors based on `wan_loopbacks`, `wan_bgp.advertise`, and `wan_bgp.import_allow`. This ensures management traffic (SSH) remains on the underlay network.

## Handlers

| Handler | Trigger |
|---------|---------|
| `Restart strongswan` | swanctl.conf or charon.conf changes |
| `Restart frr` | frr.conf or daemon enablement changes |

## Testing

Run the smoke test with a local WAN simulator:
```bash
cd roles/wan_edge/tests
ansible-playbook -i inventories/wansim/hosts.ini smoke.yml
```

The smoke test configures a three-site hub-and-spoke topology:
- edge-sim (on-prem spoke)
- gcp-sim (hub with transit)
- azure-sim (azure spoke)

See [inventories/wansim/checks.md](tests/inventories/wansim/checks.md) for site mapping and troubleshooting commands.

## License

Code: [MIT-0](https://spdx.org/licenses/MIT-0.html)  
Documentation: [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/)

See [ADR-0115](https://docs.hybridops.studio/adr/ADR-0115-linux-edge-wan-strongswan-frr/) for architectural context and [HybridOps.Studio licensing](https://docs.hybridops.studio/briefings/legal/licensing/) for details.
