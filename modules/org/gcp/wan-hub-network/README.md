# org/gcp/wan-hub-network

Provision GCP WAN hub network baseline:

- custom VPC
- core/workload subnets
- baseline firewall rules (IAP SSH + internal RFC1918)
- state-first project binding through `project_state_ref`

## Usage

```bash
hyops preflight --env <env> --strict \
  --module org/gcp/wan-hub-network \
  --inputs "$HYOPS_CORE_ROOT/modules/org/gcp/wan-hub-network/examples/inputs.min.yml"

hyops apply --env <env> \
  --module org/gcp/wan-hub-network \
  --inputs "$HYOPS_CORE_ROOT/modules/org/gcp/wan-hub-network/examples/inputs.min.yml"
```

Preferred reusable contract:

- set `project_state_ref=org/gcp/project-factory`
- let HybridOps resolve `project_id` from upstream state
- use `project_id` only as an explicit override for external or nonstandard projects
