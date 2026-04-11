# Proxmox SDN Shared Foundation Module

Shared-authority `hyops` module for managing the Proxmox SDN foundation for a site or cluster: zone, VNets, subnets, host gateway state, optional DHCP, and downstream readiness checks.

Use this module when you want Proxmox SDN to behave like a shared platform baseline rather than per-environment config that drifts between `dev`, `staging`, and `prod`.

Default operating model (recommended):
- Deploy this module in `--env shared` as the single SDN authority for the Proxmox cluster/site.
- Other envs (`dev`, `staging`, `prod`) consume the shared SDN/NetBox authority and should not re-deploy SDN.
- Non-shared SDN deploys are blocked by default; override intentionally with `allow_non_shared_env: true`.

What this gives you:
- one shared owner for SDN topology
- fail-fast validation after apply, not just "Terraform finished"
- optional NetBox/IPAM export from the same authority

`hyops apply` runs a live post-apply SDN readiness validation by default (fail-fast). It verifies:
- the expected Proxmox SDN zone exists
- the expected VNet(s) exist
- the expected host gateway IP(s) (for example `10.12.0.1/24`) are present on the VNet device(s)

This prevents downstream VM modules from proceeding when SDN partially converged or state drift hides a broken gateway path.

When Proxmox is running in host-routed mode and a separate on-prem edge owns
cloud or WAN reachability, use `host_static_routes` to teach the Proxmox host
gateway where those upstream prefixes live. This is the supported pattern for
site-extension designs where guests still use the Proxmox host as their default
gateway. For greenfield sites, or when guest default gateways can be migrated
cleanly, prefer the edge-routed model instead of extending host-routed mode.

By default, `execution.hooks.export_infra.push_to_netbox=true` is enabled (non-strict).
If NetBox authority is ready and `NETBOX_API_TOKEN` is available, apply exports/syncs the
IPAM prefix dataset into NetBox. Before NetBox exists, the hook degrades to a warning and
continues.

## Usage

```bash
hyops preflight --env <env> --strict \
  --module core/onprem/network-sdn \
  --inputs "modules/core/onprem/network-sdn/examples/inputs.min.yml"

hyops apply --env <env> \
  --module core/onprem/network-sdn \
  --inputs "modules/core/onprem/network-sdn/examples/inputs.min.yml"
```

Recommended shared foundation deployment (ADR-0101 VLAN layout):

```bash
hyops apply --env shared \
  --module core/onprem/network-sdn \
  --inputs "modules/core/onprem/network-sdn/examples/inputs.shared.full.yml"
```

Optional tuning (strict by default):

```yaml
post_apply_sdn_readiness:
  enabled: true      # default
  required: true     # default
  timeout_s: 10      # per SSH probe to the Proxmox host
  settle_wait_s: 5   # wait after apply before live checks

# Break-glass only (default is shared-only enforcement)
# allow_non_shared_env: true

# Optional host-routed upstream prefixes
# host_static_routes:
#   - destination_cidr: "10.72.0.0/20"
#     next_hop: "10.10.0.20"
#   - destination_cidr: "10.72.16.0/20"
#     next_hop: "10.10.0.20"
#   - destination_cidr: "10.74.0.0/18"
#     next_hop: "10.10.0.20"
```

### Recovery (host-side SDN drift, same topology)

If Proxmox host-side SDN state drifts (for example `vnetdata` exists but the expected
gateway IP is missing) and your topology inputs are unchanged, use an explicit one-time
reconcile token instead of changing unrelated settings:

```bash
HYOPS_INPUT_host_reconcile_nonce="$(date -u +%Y%m%dT%H%M%SZ)" \
hyops apply --env shared \
  --module core/onprem/network-sdn \
  --inputs "modules/core/onprem/network-sdn/examples/inputs.shared.full.yml"
```

The nonce is passed through to the underlying Terraform module and forces the host-side
gateway/NAT/DHCP reconciliation scripts to re-run without mutating the SDN topology model.

## Inputs

- `examples/inputs.min.yml`: minimal SDN overlay.
- `examples/inputs.typical.yml`: common LAN-style defaults.
- `examples/inputs.enterprise.yml`: larger/segmented ranges.
- `examples/inputs.shared.full.yml`: shared site foundation VLAN plan (ADR-0101) plus optional enterprise refinements (`vnetddev`, `vnetdstg`, `vnetdprd` on VLANs `21/31/41`).
- `host_static_routes`: optional static routes installed on the Proxmox host
  when `enable_host_l3=true`. Use this when the Proxmox host is the default
  gateway for guests but a separate on-prem edge owns cloud or WAN prefixes.

## Outputs

- `zone`
- `vnet`
- `subnet`
- `cap.network.sdn = ready`
