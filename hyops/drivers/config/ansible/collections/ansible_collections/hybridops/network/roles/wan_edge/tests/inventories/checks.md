# WAN Simulator Troubleshooting

Quick reference for debugging the three-site WAN simulator.

## Pre-flight: Verify NICs

Before updating inventory, confirm tunnel interface IPs on each host:
```bash
ssh <user>@<edge_mgmt_ip> 'ip -4 addr show <tunnel_if> | grep inet'
ssh <user>@<gcp_mgmt_ip> 'ip -4 addr show <tunnel_if> | grep inet'
ssh <user>@<azure_mgmt_ip> 'ip -4 addr show <tunnel_if> | grep inet'
```

Update `wan_public_local_ip` and peer IPs in group_vars to match actual output.

## Site Mapping Template

| Role | Hostname | Mgmt IP | Tunnel IF | Tunnel IP | Loopback | ASN |
|------|----------|---------|-----------|-----------|----------|-----|
| On-prem (spoke) | edge-sim | `<edge_mgmt>` | `<if>` | `<edge_tun>` | 10.110.0.1/24 | 65010 |
| GCP (hub) | gcp-sim | `<gcp_mgmt>` | `<if>` | `<gcp_tun>` | 10.70.0.1/20 | 64514 |
| Azure (spoke) | azure-sim | `<azure_mgmt>` | `<if>` | `<azure_tun>` | 10.80.0.1/24 | 65020 |

## Tunnel Endpoints Template

### edge-sim → gcp-sim

| Tunnel | Local IP | Peer IP | Inside Local | Inside Peer | Key |
|--------|----------|---------|--------------|-------------|-----|
| tunnel_a | `<edge_tun>` | `<gcp_tun>` | 169.254.10.1/30 | 169.254.10.2 | 10 |
| tunnel_b | `<edge_tun>` | `<gcp_alias_1>` | 169.254.10.5/30 | 169.254.10.6 | 11 |

### gcp-sim → azure-sim

| Tunnel | Local IP | Peer IP | Inside Local | Inside Peer | Key |
|--------|----------|---------|--------------|-------------|-----|
| azure_a | `<gcp_alias_2>` | `<azure_tun>` | 169.254.20.1/30 | 169.254.20.2 | 20 |
| azure_b | `<gcp_alias_3>` | `<azure_alias_1>` | 169.254.20.5/30 | 169.254.20.6 | 21 |

### Alias Planning

The hub (gcp-sim) requires additional IPs for multi-tunnel endpoints:
```
<gcp_tun>      - primary (DHCP assigned)
<gcp_alias_1>  - onprem tunnel_b  (wan_public_aliases[0])
<gcp_alias_2>  - azure tunnel_a   (wan_public_aliases[1])
<gcp_alias_3>  - azure tunnel_b   (wan_public_aliases[2])
```

Azure spoke needs one alias for tunnel_b:
```
<azure_tun>     - primary (DHCP assigned)
<azure_alias_1> - tunnel_b (wan_public_aliases[0])
```

---

## Example: Lab Environment

Discovered IPs from pre-flight check:
```bash
$ ssh hybridops@10.10.0.132 'ip -4 addr show eth1 | grep inet'
    inet 10.50.0.142/24 ...
$ ssh hybridops@10.10.0.151 'ip -4 addr show eth1 | grep inet'
    inet 10.50.0.149/24 ...
$ ssh hybridops@10.10.0.181 'ip -4 addr show eth1 | grep inet'
    inet 10.50.0.132/24 ...
```

### Populated Site Mapping

| Role | Hostname | Mgmt IP | Tunnel IF | Tunnel IP | Loopback | ASN |
|------|----------|---------|-----------|-----------|----------|-----|
| On-prem (spoke) | edge-sim | 10.10.0.132 | eth1 | 10.50.0.142 | 10.110.0.1/24 | 65010 |
| GCP (hub) | gcp-sim | 10.10.0.151 | eth1 | 10.50.0.149 | 10.70.0.1/20 | 64514 |
| Azure (spoke) | azure-sim | 10.10.0.181 | eth1 | 10.50.0.132 | 10.80.0.1/24 | 65020 |

### Populated Tunnel Endpoints

**edge-sim → gcp-sim:**

| Tunnel | Local IP | Peer IP | Inside Local | Inside Peer | Key |
|--------|----------|---------|--------------|-------------|-----|
| tunnel_a | 10.50.0.142 | 10.50.0.149 | 169.254.10.1/30 | 169.254.10.2 | 10 |
| tunnel_b | 10.50.0.142 | 10.50.0.150 | 169.254.10.5/30 | 169.254.10.6 | 11 |

**gcp-sim → azure-sim:**

| Tunnel | Local IP | Peer IP | Inside Local | Inside Peer | Key |
|--------|----------|---------|--------------|-------------|-----|
| azure_a | 10.50.0.151 | 10.50.0.132 | 169.254.20.1/30 | 169.254.20.2 | 20 |
| azure_b | 10.50.0.152 | 10.50.0.133 | 169.254.20.5/30 | 169.254.20.6 | 21 |

**Alias assignments:**
```
gcp-sim aliases:   10.50.0.150, 10.50.0.151, 10.50.0.152
azure-sim aliases: 10.50.0.133
```

---

## Quick Checks

### IPsec Status
```bash
# List SAs (should show ESTABLISHED + INSTALLED)
swanctl --list-sas

# Count CHILD_SAs
swanctl --list-sas | grep -c "INSTALLED, TUNNEL"
```

### BGP Status
```bash
# Summary
vtysh -c "show bgp summary"

# Routes received
vtysh -c "show bgp ipv4 unicast"

# Specific route
vtysh -c "show ip route 10.110.0.0/24"
```

### Routing
```bash
# Kernel route table
ip route show proto bgp

# Route lookup
ip route get 10.110.0.1

# Check for stale routes in table 220
ip route show table 220
```

### Connectivity
```bash
# Ping with source (use loopback, not VTI inside IP)
ping -c 2 -I <local_loopback> <remote_loopback>

# Example: azure to onprem
ping -c 2 -I 10.80.0.1 10.110.0.1
```

## Common Issues

| Symptom | Check | Fix |
|---------|-------|-----|
| `bgpd is not running` | `grep bgpd /etc/frr/daemons` | Set `bgpd=yes`, restart frr |
| Tunnels stuck CONNECTING | `swanctl --list-sas` | Check PSK, peer IPs, firewall |
| ICMP Redirect errors | `sysctl net.ipv4.conf.all.send_redirects` | Set to 0 on hub |
| Route via wrong interface | `ip route show table 220` | Delete stale static routes |
| Ping fails from VTI IP | Use `-I <loopback>` | Source must be in traffic selectors |
| Transit routing fails | `vtysh -c "show ip route <prefix>"` | Check `import_allow` includes transit prefixes |

## XFRM Debugging
```bash
# Show policies for specific prefix
ip xfrm policy | grep -A3 "<prefix>"

# Show states with stats
ip -s xfrm state

# Watch for errors
ip xfrm monitor
```

## Tcpdump Examples
```bash
# ESP packets on tunnel interface
tcpdump -i <tunnel_if> esp

# ICMP on VTI
tcpdump -i vti10 icmp

# All ICMP to specific host
tcpdump -i any icmp and host <target_ip>
```