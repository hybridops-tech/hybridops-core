# org/gcp/wan-cloud-nat

Provision Cloud NAT for explicitly selected private subnets in the GCP hub VPC.

This module is the provider-specific egress layer for private GCP runners and other
private workloads that need outbound HTTPS without public IPs.

## Usage

```bash
hyops preflight --env <env> --strict \
  --module org/gcp/wan-cloud-nat \
  --inputs "$HYOPS_CORE_ROOT/modules/org/gcp/wan-cloud-nat/examples/inputs.min.yml"

hyops apply --env <env> \
  --module org/gcp/wan-cloud-nat \
  --inputs "$HYOPS_CORE_ROOT/modules/org/gcp/wan-cloud-nat/examples/inputs.min.yml"
```

## Contract

- prefer `router_state_ref` to consume the Cloud Router contract from state
- prefer `network_state_ref` + `subnetwork_output_keys` to consume explicit subnets from state
- `subnetwork_source_ip_ranges_to_nat` controls what NAT covers inside the selected subnets
- keep NAT explicit per subnet group; do not silently NAT every subnet by default

This keeps the pattern reusable for GCP runner blueprints and later private workload blueprints.
