# org/gcp/wan-hub-network

Provision GCP WAN hub network baseline:

- custom VPC
- core/workload subnets
- baseline firewall rules (IAP SSH + internal RFC1918)

## Usage

```bash
hyops preflight --env <env> --strict \
  --module org/gcp/wan-hub-network \
  --inputs "$HYOPS_CORE_ROOT/modules/org/gcp/wan-hub-network/examples/inputs.min.yml"

hyops apply --env <env> \
  --module org/gcp/wan-hub-network \
  --inputs "$HYOPS_CORE_ROOT/modules/org/gcp/wan-hub-network/examples/inputs.min.yml"
```
