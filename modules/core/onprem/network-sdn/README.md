# core/onprem/network-sdn

Configure Proxmox SDN foundation (zone, VNet, subnet, DHCP range) via Terragrunt.

Default operating model (recommended):
- Deploy this module in `--env shared` as the single SDN authority for the Proxmox cluster/site.
- Other envs (`dev`, `staging`, `prod`) consume the shared SDN/NetBox authority and should not re-deploy SDN.
- Non-shared SDN deploys are blocked by default; override intentionally with `allow_non_shared_env: true`.

`hyops apply` runs a live post-apply SDN readiness validation by default (fail-fast). It verifies:
- the expected Proxmox SDN zone exists
- the expected VNet(s) exist
- the expected host gateway IP(s) (for example `10.12.0.1/24`) are present on the VNet device(s)

This prevents downstream VM modules from proceeding when SDN partially converged or state drift hides a broken gateway path.

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

## Outputs

- `zone`
- `vnet`
- `subnet`
- `cap.network.sdn = ready`
