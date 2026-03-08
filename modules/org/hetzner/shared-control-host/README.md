# org/hetzner/shared-control-host

Provision a dedicated Hetzner VM on the WAN private network for shared control-plane services. This keeps PowerDNS, decision service, and similar components off the WAN edge appliances.

State-first defaults:

- `foundation_state_ref`: resolves `private_network_id` and `private_network_cidr` from `org/hetzner/vyos-edge-foundation`
- `ssh_keys_from_init: true`: resolves `ssh_keys` from `hyops init hetzner` readiness metadata

The module creates:

- one `hcloud_server`
- one SSH-only firewall on the public interface
- cloud-init to create a stable `opsadmin` automation user
- first-boot netplan normalization for the Hetzner private NIC using the routed
  cloud-network model (`private_ip/32` plus route to `private_network_cidr`
  via the network gateway)

The module intentionally avoids creating duplicate Hetzner project SSH key objects. Access is established through cloud-init using the public key resolved from `hyops init hetzner` or explicitly supplied in `inputs.ssh_keys`.

Example:

```bash
hyops validate --env dev --skip-preflight \
  --module org/hetzner/shared-control-host \
  --inputs "$HYOPS_CORE_ROOT/modules/org/hetzner/shared-control-host/examples/inputs.min.yml"
```
